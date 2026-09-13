from __future__ import annotations

from typing import Any

from control_plane.models import ChangeRecord, LlmReview
from control_plane.policy import blast_rank


def _latency_exceeds(request: dict[str, Any], policy: dict[str, Any], llm: LlmReview) -> bool:
    services = {str(item) for item in (policy.get("latency_sensitive_services") or [])}
    if str(request.get("service")) not in services:
        return False
    ceiling = policy.get("max_latency_impact_auto_approve_ms")
    if ceiling is None or llm.estimated_latency_impact_ms is None:
        return False
    try:
        return float(llm.estimated_latency_impact_ms) > float(ceiling)
    except (TypeError, ValueError):
        return True


def reconcile(record: ChangeRecord, policy: dict[str, Any]) -> None:
    policy_eval = record.policy
    llm = record.llm
    if policy_eval is None:
        record.system_recommendation = "block"
        record.system_rationale = ["missing_policy_evaluation"]
        return

    reasons: list[str] = []
    decision = "auto_approve"

    def escalate(target: str, reason: str) -> None:
        nonlocal decision
        rank = {"auto_approve": 0, "human_review": 1, "block": 2}
        if rank[target] > rank[decision]:
            decision = target
        reasons.append(reason)

    if policy_eval.has_mandatory_block:
        for code in policy_eval.blockers:
            escalate("block", f"mandatory_policy_blocker:{code}")

    if llm is None or not llm.valid:
        escalate("block", "llm_review_incomplete")
        if llm is not None:
            for err in llm.parse_errors:
                reasons.append(f"llm_error:{err}")
    else:
        if llm.recommendation == "block":
            escalate("block", "llm_recommends_block")
        if llm.risk_level in {"high", "critical"}:
            escalate("human_review", f"llm_risk:{llm.risk_level}")
        if llm.confidence == "low":
            escalate("human_review", "llm_confidence_low")
        if llm.recommendation == "human_review":
            escalate("human_review", "llm_recommends_human_review")
        if _latency_exceeds(record.original_request, policy, llm):
            escalate("human_review", "latency_impact_exceeds_auto_approve")
        if llm.testing_adequacy == "insufficient":
            escalate("human_review", "llm_testing_inadequate")
        if llm.justification_adequacy == "weak":
            escalate("human_review", "llm_justification_weak")

    for code in policy_eval.human_review_reasons:
        escalate("human_review", f"policy_human_review:{code}")

    if decision == "auto_approve":
        reasons.append("all_mandatory_gates_passed")
        reasons.append("llm_review_completed")
        if llm is not None and llm.confidence:
            reasons.append(f"llm_confidence:{llm.confidence}")

    record.system_recommendation = decision
    record.system_rationale = reasons
    record.final_decision = decision
    record.executable = False


def canary_required(request: dict[str, Any], policy: dict[str, Any]) -> bool:
    production = str(request.get("environment", "")).lower() == "production"
    max_blast = policy.get("max_auto_approve_blast_radius")
    wider_than_single = False
    if max_blast is not None:
        wider_than_single = blast_rank(request.get("blast_radius"), policy) > blast_rank(max_blast, policy)
    else:
        wider_than_single = blast_rank(request.get("blast_radius"), policy) > blast_rank("single_service", policy)
    return production and (wider_than_single or str(request.get("request_type")) == "code_deployment")
