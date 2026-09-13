from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from control_plane.models import ChangeRecord, HumanOutcome


def load_human_reviews(input_dir: Path) -> list[dict[str, Any]]:
    path = input_dir / "human_reviews.json"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError("human_reviews.json must be a JSON array")
    return [item for item in raw if isinstance(item, dict)]


def matching_review(record: ChangeRecord, reviews: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reviews:
        if str(item.get("request_id")) != record.request_id:
            continue
        return item
    return None


def apply_human_review(record: ChangeRecord, review: dict[str, Any] | None) -> None:
    if review is None:
        record.human = HumanOutcome(
            action="pending",
            justification="",
            reviewer="",
            bound_request_hash=record.request_hash,
            bound_policy_hash=record.policy_hash,
            bound_context_hash=record.context_hash,
            binding_ok=True,
            notes="No bound human decision supplied; remaining in human_review.",
        )
        record.final_decision = "human_review"
        record.executable = False
        return

    action = str(review.get("action", "")).lower()
    justification = str(review.get("justification") or "").strip()
    reviewer = str(review.get("reviewer") or "human")
    bound_request = str(review.get("request_hash") or record.request_hash)
    bound_policy = str(review.get("policy_hash") or "")
    bound_context = str(review.get("context_hash") or "")

    binding_ok = bound_request == record.request_hash
    if bound_policy and bound_policy != record.policy_hash:
        binding_ok = False
    if bound_context and bound_context != record.context_hash:
        binding_ok = False

    notes: list[str] = []
    if not justification:
        notes.append("missing_justification")
    if action not in {"approve", "reject", "request_evidence"}:
        notes.append("invalid_action")
        action = "pending"
    if not binding_ok:
        notes.append("binding_mismatch")

    record.human = HumanOutcome(
        action=action if binding_ok and action in {"approve", "reject", "request_evidence"} else "pending",
        justification=justification,
        reviewer=reviewer,
        bound_request_hash=bound_request,
        bound_policy_hash=bound_policy or record.policy_hash,
        bound_context_hash=bound_context or record.context_hash,
        binding_ok=binding_ok,
        notes=";".join(notes),
    )

    # Humans never overwrite the machine recommendation.
    record.final_decision = record.system_recommendation
    record.executable = False

    if not binding_ok or "missing_justification" in notes or "invalid_action" in notes:
        record.closed_reason = "human_decision_rejected_fail_closed"
        return

    if action == "request_evidence":
        record.closed_reason = "additional_evidence_requested"
        record.final_decision = "human_review"
        return

    if action == "reject":
        record.final_decision = "block"
        record.closed_reason = "human_rejected"
        return

    if action == "approve":
        if record.system_recommendation == "block":
            record.closed_reason = "human_cannot_override_mandatory_block"
            record.final_decision = "block"
            record.executable = False
            return
        record.final_decision = "human_review"
        record.closed_reason = "human_approved"
        record.executable = True
