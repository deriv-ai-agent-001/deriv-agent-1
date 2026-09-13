from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class State(str, Enum):
    INGESTED = "INGESTED"
    POLICY_CHECKED = "POLICY_CHECKED"
    LLM_REVIEWED = "LLM_REVIEWED"
    DECISION_RECONCILED = "DECISION_RECONCILED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    FINALISED = "FINALISED"
    PRECONDITION_CHECKED = "PRECONDITION_CHECKED"
    EXECUTION_AUTHORIZED = "EXECUTION_AUTHORIZED"
    PREPARED = "PREPARED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    INCIDENT_ESCALATED = "INCIDENT_ESCALATED"


ALLOWED_TRANSITIONS: dict[State, frozenset[State]] = {
    State.INGESTED: frozenset({State.POLICY_CHECKED}),
    State.POLICY_CHECKED: frozenset({State.LLM_REVIEWED, State.FINALISED}),
    State.LLM_REVIEWED: frozenset({State.DECISION_RECONCILED}),
    State.DECISION_RECONCILED: frozenset({State.HUMAN_REVIEW_REQUIRED, State.FINALISED}),
    State.HUMAN_REVIEW_REQUIRED: frozenset({State.FINALISED, State.POLICY_CHECKED}),
    State.FINALISED: frozenset({State.PRECONDITION_CHECKED}),
    State.PRECONDITION_CHECKED: frozenset({State.EXECUTION_AUTHORIZED, State.FINALISED}),
    State.EXECUTION_AUTHORIZED: frozenset({State.PREPARED}),
    State.PREPARED: frozenset({State.EXECUTING}),
    State.EXECUTING: frozenset({State.VERIFIED, State.EXECUTION_FAILED}),
    State.EXECUTION_FAILED: frozenset({State.ROLLBACK_PENDING}),
    State.ROLLBACK_PENDING: frozenset({State.ROLLING_BACK}),
    State.ROLLING_BACK: frozenset({State.ROLLED_BACK, State.ROLLBACK_FAILED}),
    State.ROLLBACK_FAILED: frozenset({State.INCIDENT_ESCALATED}),
    State.VERIFIED: frozenset(),
    State.ROLLED_BACK: frozenset(),
    State.INCIDENT_ESCALATED: frozenset(),
}


class InvalidTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class StageEvent:
    from_state: str | None
    to_state: str
    at: str
    reason: str
    actor: str = "system"

    def to_dict(self) -> dict:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "at": self.at,
            "reason": self.reason,
            "actor": self.actor,
        }


class StateMachine:
    def __init__(self, initial: State | None = None) -> None:
        self.current: State | None = initial
        self.history: list[StageEvent] = []

    def enter(self, target: State, reason: str, actor: str = "system") -> None:
        if self.current is None:
            if target != State.INGESTED:
                raise InvalidTransition(f"first state must be INGESTED, not {target.value}")
        else:
            allowed = ALLOWED_TRANSITIONS.get(self.current, frozenset())
            if target not in allowed:
                raise InvalidTransition(
                    f"illegal transition {self.current.value} -> {target.value}"
                )
        event = StageEvent(
            from_state=None if self.current is None else self.current.value,
            to_state=target.value,
            at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            actor=actor,
        )
        self.history.append(event)
        self.current = target

    def restore(self, history: list[dict], current: str | None) -> None:
        self.history = [
            StageEvent(
                from_state=item.get("from_state"),
                to_state=str(item.get("to_state")),
                at=str(item.get("at") or ""),
                reason=str(item.get("reason") or ""),
                actor=str(item.get("actor") or "system"),
            )
            for item in history
        ]
        self.current = State(current) if current else None

    def require(self, *states: State) -> None:
        if self.current not in states:
            found = None if self.current is None else self.current.value
            expected = ", ".join(s.value for s in states)
            raise InvalidTransition(f"expected state in [{expected}], found {found}")
