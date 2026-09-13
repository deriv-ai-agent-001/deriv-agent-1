from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from control_plane.hashes import sha256_hex
from control_plane.models import ChangeRecord, ExecutionRecord
from control_plane.policy import evaluate_policy, incident_exception_active
from control_plane.reconcile import canary_required
from control_plane.states import State


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _precondition(
    code: str,
    ok: bool,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"code": code, "ok": ok, "message": message, "details": details or {}}


def authorize_and_execute(
    record: ChangeRecord,
    policy: dict[str, Any],
    context: dict[str, Any],
    *,
    occupied_services: set[str],
    execute: bool,
) -> None:
    request = record.original_request
    notes: list[str] = []
    preconditions: list[dict[str, Any]] = []
    snapshot = {
        "service": request.get("service"),
        "proposed_change": request.get("proposed_change"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    canary = canary_required(request, policy)

    record.machine.require(State.FINALISED)
    if not record.executable or record.final_decision == "block":
        record.execution = ExecutionRecord(
            authorized=False,
            executable=False,
            authorization_id=None,
            canary_required=canary,
            snapshot=snapshot,
            result="skipped",
            failure_reason="not_executable",
            rollback_result=None,
            preconditions=[],
            notes=["execution skipped because the finalised decision is not executable"],
        )
        return

    if not execute:
        record.execution = ExecutionRecord(
            authorized=False,
            executable=True,
            authorization_id=None,
            canary_required=canary,
            snapshot=snapshot,
            result="pending_authorization",
            failure_reason=None,
            rollback_result=None,
            preconditions=[],
            notes=["evaluate-only run; approval is not permanent and execution was not requested"],
        )
        return

    record.machine.enter(State.PRECONDITION_CHECKED, "fresh execution precondition check")

    live_request_hash = sha256_hex(request)
    live_policy_hash = sha256_hex(policy)
    live_context_hash = sha256_hex(context)
    fresh = evaluate_policy(
        request,
        policy,
        context,
        record.ingest_errors,
        live_request_hash,
        live_policy_hash,
        live_context_hash,
    )
    version_ok = (
        live_policy_hash == record.policy_hash
        and live_context_hash == record.context_hash
        and live_request_hash == record.request_hash
    )
    preconditions.append(
        _precondition(
            "version_binding",
            version_ok,
            "Request, policy, and context fingerprints still match the approved evaluation.",
            {
                "request_hash": record.request_hash,
                "policy_hash": record.policy_hash,
                "context_hash": record.context_hash,
            },
        )
    )
    if fresh.has_mandatory_block:
        preconditions.append(
            _precondition(
                "fresh_policy",
                False,
                "Fresh policy evaluation introduced mandatory blockers.",
                {"blockers": fresh.blockers},
            )
        )
    else:
        preconditions.append(
            _precondition("fresh_policy", True, "Fresh policy evaluation has no mandatory blockers.")
        )

    approval_ttl = policy.get("approval_ttl_seconds")
    if approval_ttl is not None:
        ingested_at = record.machine.history[0].at if record.machine.history else None
        expired = False
        if ingested_at:
            try:
                started = datetime.fromisoformat(ingested_at)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                expired = elapsed > float(approval_ttl)
            except (TypeError, ValueError):
                expired = True
        preconditions.append(
            _precondition(
                "approval_ttl",
                not expired,
                "Approval is within configured TTL." if not expired else "Approval has expired.",
                {"approval_ttl_seconds": approval_ttl},
            )
        )

    service = str(request.get("service", ""))
    concurrency_ok = service not in occupied_services
    preconditions.append(
        _precondition(
            "concurrency",
            concurrency_ok,
            "No other in-flight execution for this service."
            if concurrency_ok
            else "Service already has an in-flight execution.",
            {"service": service},
        )
    )

    production = str(request.get("environment", "")).lower() == "production"
    rollback_ok = True
    if production and _as_bool(policy.get("production_requires_rollback"), False):
        rollback_ok = _as_bool(request.get("rollback_defined"), False)
        if not rollback_ok and incident_exception_active(request, context) and _as_bool(
            policy.get("incident_exception_allows_missing_rollback"), False
        ):
            rollback_ok = False
            notes.append("incident_exception_cannot_authorize_missing_rollback_at_execution")
    preconditions.append(
        _precondition(
            "rollback_readiness",
            rollback_ok,
            "Rollback plan is defined and ready." if rollback_ok else "Rollback plan is not ready for execution.",
            {"rollback_defined": request.get("rollback_defined")},
        )
    )

    freeze_ok = not (
        _as_bool(context.get("deployment_freeze"), False)
        and production
        and not incident_exception_active(request, context)
    )
    preconditions.append(
        _precondition("deployment_freeze", freeze_ok, "Deployment freeze does not block execution.")
    )

    all_ok = all(item["ok"] for item in preconditions)
    if not all_ok:
        record.executable = False
        record.closed_reason = "execution_preconditions_failed"
        record.execution = ExecutionRecord(
            authorized=False,
            executable=False,
            authorization_id=None,
            canary_required=canary,
            snapshot=snapshot,
            result="blocked_at_precondition",
            failure_reason="precondition_failed",
            rollback_result=None,
            preconditions=preconditions,
            notes=notes,
        )
        record.machine.enter(State.FINALISED, "execution denied after fresh precondition check")
        return

    authorization_id = sha256_hex(
        {
            "evaluation_id": record.evaluation_id,
            "service": service,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    occupied_services.add(service)
    record.machine.enter(State.EXECUTION_AUTHORIZED, "preconditions passed; execution authorized")
    record.machine.enter(State.PREPARED, "pre-change snapshot captured")
    record.machine.enter(State.EXECUTING, "applying change" + (" with canary" if canary else ""))

    forced_failure = _as_bool((request.get("proposed_change") or {}).get("simulate_execution_failure"), False)
    if forced_failure:
        record.machine.enter(State.EXECUTION_FAILED, "post-change health check failed")
        record.machine.enter(State.ROLLBACK_PENDING, "rollback required after execution failure")
        record.machine.enter(State.ROLLING_BACK, "executing rollback plan")
        if _as_bool(request.get("rollback_defined"), False):
            record.machine.enter(State.ROLLED_BACK, "rollback completed")
            rollback_result = "rolled_back"
            result = "failed_rolled_back"
        else:
            record.machine.enter(State.ROLLBACK_FAILED, "rollback plan missing or unsuccessful")
            record.machine.enter(State.INCIDENT_ESCALATED, "failed rollback escalated")
            rollback_result = "rollback_failed"
            result = "failed_rollback_failed"
        record.execution = ExecutionRecord(
            authorized=True,
            executable=True,
            authorization_id=authorization_id,
            canary_required=canary,
            snapshot=snapshot,
            result=result,
            failure_reason="simulated_or_observed_health_failure",
            rollback_result=rollback_result,
            preconditions=preconditions,
            notes=notes,
        )
        occupied_services.discard(service)
        return

    record.machine.enter(State.VERIFIED, "post-change health checks passed")
    record.execution = ExecutionRecord(
        authorized=True,
        executable=True,
        authorization_id=authorization_id,
        canary_required=canary,
        snapshot=snapshot,
        result="verified",
        failure_reason=None,
        rollback_result=None,
        preconditions=preconditions,
        notes=notes + (["canary_completed"] if canary else []),
    )
    occupied_services.discard(service)
