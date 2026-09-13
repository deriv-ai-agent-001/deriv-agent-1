from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from control_plane.hashes import sha256_hex
from control_plane.states import State, StateMachine


REQUIRED_REQUEST_FIELDS = (
    "id",
    "title",
    "request_type",
    "service",
    "environment",
    "requested_by",
    "summary",
    "proposed_change",
    "blast_radius",
    "rollback_defined",
    "test_evidence",
    "change_window",
    "llm_generated",
)

VALID_DECISIONS = frozenset({"auto_approve", "human_review", "block"})
VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
VALID_CONFIDENCE = frozenset({"low", "medium", "high"})

DEFAULT_BLAST_RADIUS_ORDER = (
    "internal_only",
    "single_service",
    "multi_service",
    "multi_region",
    "global",
)


@dataclass
class PolicyCheck:
    code: str
    outcome: str  # pass | human_review | block
    mandatory: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "outcome": self.outcome,
            "mandatory": self.mandatory,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class PolicyEvaluation:
    request_id: str
    request_hash: str
    policy_hash: str
    context_hash: str
    deterministic_risk: str
    checks: list[PolicyCheck]
    blockers: list[str]
    human_review_reasons: list[str]
    ingest_errors: list[str]

    @property
    def has_mandatory_block(self) -> bool:
        return bool(self.blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "policy_hash": self.policy_hash,
            "context_hash": self.context_hash,
            "deterministic_risk": self.deterministic_risk,
            "checks": [c.to_dict() for c in self.checks],
            "blockers": list(self.blockers),
            "human_review_reasons": list(self.human_review_reasons),
            "ingest_errors": list(self.ingest_errors),
        }


@dataclass
class LlmReview:
    request_id: str
    valid: bool
    replayed: bool
    model: str
    prompt_hash: str
    response_hash: str
    risk_level: str | None
    confidence: str | None
    recommendation: str | None
    estimated_latency_impact_ms: float | None
    reversibility: str | None
    testing_adequacy: str | None
    justification_adequacy: str | None
    hidden_failure_modes: list[str]
    rationale: str
    parse_errors: list[str]
    raw_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "valid": self.valid,
            "replayed": self.replayed,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "estimated_latency_impact_ms": self.estimated_latency_impact_ms,
            "reversibility": self.reversibility,
            "testing_adequacy": self.testing_adequacy,
            "justification_adequacy": self.justification_adequacy,
            "hidden_failure_modes": list(self.hidden_failure_modes),
            "rationale": self.rationale,
            "parse_errors": list(self.parse_errors),
        }


@dataclass
class HumanOutcome:
    action: str  # approve | reject | request_evidence | pending
    justification: str
    reviewer: str
    bound_request_hash: str
    bound_policy_hash: str
    bound_context_hash: str
    binding_ok: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "justification": self.justification,
            "reviewer": self.reviewer,
            "bound_request_hash": self.bound_request_hash,
            "bound_policy_hash": self.bound_policy_hash,
            "bound_context_hash": self.bound_context_hash,
            "binding_ok": self.binding_ok,
            "notes": self.notes,
        }


@dataclass
class ExecutionRecord:
    authorized: bool
    executable: bool
    authorization_id: str | None
    canary_required: bool
    snapshot: dict[str, Any]
    result: str | None
    failure_reason: str | None
    rollback_result: str | None
    preconditions: list[dict[str, Any]]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "executable": self.executable,
            "authorization_id": self.authorization_id,
            "canary_required": self.canary_required,
            "snapshot": self.snapshot,
            "result": self.result,
            "failure_reason": self.failure_reason,
            "rollback_result": self.rollback_result,
            "preconditions": list(self.preconditions),
            "notes": list(self.notes),
        }


@dataclass
class ChangeRecord:
    original_request: dict[str, Any]
    request_id: str
    evaluation_id: str
    request_hash: str
    policy_hash: str
    context_hash: str
    machine: StateMachine
    ingest_errors: list[str] = field(default_factory=list)
    policy: PolicyEvaluation | None = None
    llm: LlmReview | None = None
    system_recommendation: str | None = None
    system_rationale: list[str] = field(default_factory=list)
    final_decision: str | None = None
    human: HumanOutcome | None = None
    executable: bool = False
    execution: ExecutionRecord | None = None
    closed_reason: str | None = None

    @property
    def state(self) -> State | None:
        return self.machine.current

    def to_final_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "policy_hash": self.policy_hash,
            "context_hash": self.context_hash,
            "current_state": None if self.state is None else self.state.value,
            "original_request": self.original_request,
            "ingest_errors": list(self.ingest_errors),
            "policy_evaluation": None if self.policy is None else self.policy.to_dict(),
            "llm_review": None if self.llm is None else self.llm.to_dict(),
            "system_recommendation": self.system_recommendation,
            "system_rationale": list(self.system_rationale),
            "human_outcome": None if self.human is None else self.human.to_dict(),
            "final_decision": self.final_decision,
            "executable": self.executable,
            "closed_reason": self.closed_reason,
            "execution": None if self.execution is None else self.execution.to_dict(),
            "stage_history": [e.to_dict() for e in self.machine.history],
        }


def request_id_of(payload: Any) -> str:
    if isinstance(payload, dict) and payload.get("id") not in (None, ""):
        return str(payload["id"])
    return sha256_hex(payload)[:16]
