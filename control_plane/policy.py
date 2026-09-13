from __future__ import annotations

from typing import Any, Iterable

from control_plane.models import (
    DEFAULT_BLAST_RADIUS_ORDER,
    PolicyCheck,
    PolicyEvaluation,
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_str_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def blast_radius_order(policy: dict[str, Any]) -> tuple[str, ...]:
    configured = policy.get("blast_radius_order")
    if isinstance(configured, list) and configured:
        return tuple(str(item) for item in configured)
    return DEFAULT_BLAST_RADIUS_ORDER


def blast_rank(value: Any, policy: dict[str, Any]) -> int:
    order = blast_radius_order(policy)
    token = str(value)
    if token in order:
        return order.index(token)
    return len(order)


def evidence_tokens(request: dict[str, Any]) -> set[str]:
    return {str(item) for item in _as_list(request.get("test_evidence"))}


def required_evidence_for(request: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    mapping = policy.get("required_evidence_by_type") or {}
    if not isinstance(mapping, dict):
        return []
    req_type = str(request.get("request_type", ""))
    return _as_str_list(mapping.get(req_type, []))


def incident_exception_active(request: dict[str, Any], context: dict[str, Any]) -> bool:
    window = str(request.get("change_window", ""))
    return window == "incident_exception" and _as_bool(context.get("current_incident"), False)


def has_simulation_evidence(request: dict[str, Any], policy: dict[str, Any]) -> bool:
    evidence = evidence_tokens(request)
    required = set(required_evidence_for(request, policy))
    simulation_tokens = {token for token in required if "simulation" in token.lower()}
    if simulation_tokens:
        return bool(evidence & simulation_tokens)
    return any("simulation_passed" in token or token.endswith("simulation_passed") for token in evidence) or (
        "simulation_passed" in evidence
    )


def deterministic_risk(request: dict[str, Any], policy: dict[str, Any], context: dict[str, Any]) -> str:
    score = 0
    environment = str(request.get("environment", "")).lower()
    if environment == "production":
        score += 2
    elif environment not in {"staging", "dev", "development", "test"}:
        score += 1
    score += min(3, blast_rank(request.get("blast_radius"), policy))
    if str(request.get("request_type")) in set(_as_str_list(policy.get("high_risk_request_types"))):
        score += 2
    if str(request.get("service")) in set(_as_str_list(policy.get("protected_services"))) and environment == "production":
        score += 2
    if environment == "production" and not _as_bool(request.get("rollback_defined"), False):
        score += 3
    if _as_bool(request.get("llm_generated"), False):
        score += 1
    if _as_bool(context.get("current_incident"), False):
        score += 1
    if str(context.get("market_volatility", "")).lower() == "high" and environment == "production":
        score += 1
    if score >= 8:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _add(
    checks: list[PolicyCheck],
    blockers: list[str],
    reviews: list[str],
    check: PolicyCheck,
) -> None:
    checks.append(check)
    if check.outcome == "block":
        blockers.append(check.code)
    elif check.outcome == "human_review":
        reviews.append(check.code)


def evaluate_policy(
    request: dict[str, Any],
    policy: dict[str, Any],
    context: dict[str, Any],
    ingest_errors: Iterable[str],
    request_hash: str,
    policy_hash: str,
    context_hash: str,
) -> PolicyEvaluation:
    checks: list[PolicyCheck] = []
    blockers: list[str] = []
    reviews: list[str] = []
    ingest_list = [str(item) for item in ingest_errors]

    if ingest_list:
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="ingest_invalid",
                outcome="block",
                mandatory=True,
                message="Request failed schema validation and cannot leave fail-closed ingest.",
                details={"errors": ingest_list},
            ),
        )

    environment = str(request.get("environment", ""))
    req_type = str(request.get("request_type", ""))
    service = str(request.get("service", ""))
    production = environment.lower() == "production"
    freeze = _as_bool(context.get("deployment_freeze"), False)
    exception = incident_exception_active(request, context)
    claimed_exception = str(request.get("change_window", "")) == "incident_exception"

    if claimed_exception and not _as_bool(context.get("current_incident"), False):
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="invalid_incident_exception",
                outcome="block",
                mandatory=True,
                message="Incident-exception window is not valid without an active incident.",
                details={"change_window": request.get("change_window"), "current_incident": context.get("current_incident")},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="incident_exception_window",
                outcome="pass",
                mandatory=False,
                message="Incident exception window is consistent with system context."
                if claimed_exception
                else "Standard change window.",
                details={"active": exception},
            )
        )

    if freeze and production and not exception:
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="deployment_freeze",
                outcome="block",
                mandatory=True,
                message="Production change blocked by deployment freeze.",
                details={"deployment_freeze": True},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="deployment_freeze",
                outcome="pass",
                mandatory=True,
                message="No blocking deployment freeze for this request.",
                details={"deployment_freeze": freeze, "exception": exception},
            )
        )

    protected = set(_as_str_list(policy.get("protected_services")))
    if service in protected and production:
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="protected_service",
                outcome="human_review",
                mandatory=False,
                message="Protected production service requires human review.",
                details={"service": service},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="protected_service",
                outcome="pass",
                mandatory=False,
                message="Service is not a protected production target.",
                details={"service": service, "protected_services": sorted(protected)},
            )
        )

    high_risk_types = set(_as_str_list(policy.get("high_risk_request_types")))
    if req_type in high_risk_types:
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="high_risk_request_type",
                outcome="human_review",
                mandatory=False,
                message="Request type is classified as high risk.",
                details={"request_type": req_type},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="high_risk_request_type",
                outcome="pass",
                mandatory=False,
                message="Request type is not in the high-risk set.",
                details={"request_type": req_type},
            )
        )

    rollback_defined = _as_bool(request.get("rollback_defined"), False)
    requires_rollback = _as_bool(policy.get("production_requires_rollback"), False)
    if production and requires_rollback and not rollback_defined:
        allow_missing = exception and _as_bool(policy.get("incident_exception_allows_missing_rollback"), False)
        if allow_missing:
            _add(
                checks,
                blockers,
                reviews,
                PolicyCheck(
                    code="rollback_required",
                    outcome="human_review",
                    mandatory=False,
                    message="Missing rollback allowed only as an incident exception; human review required.",
                    details={"rollback_defined": False, "exception": True},
                ),
            )
        else:
            _add(
                checks,
                blockers,
                reviews,
                PolicyCheck(
                    code="rollback_required",
                    outcome="block",
                    mandatory=True,
                    message="Production change requires a defined rollback plan.",
                    details={
                        "rollback_defined": False,
                        "incident_exception_allows_missing_rollback": policy.get(
                            "incident_exception_allows_missing_rollback"
                        ),
                    },
                ),
            )
    else:
        checks.append(
            PolicyCheck(
                code="rollback_required",
                outcome="pass",
                mandatory=True,
                message="Rollback policy satisfied.",
                details={"rollback_defined": rollback_defined, "production": production},
            )
        )

    required_evidence = required_evidence_for(request, policy)
    present = evidence_tokens(request)
    missing = [item for item in required_evidence if item not in present]
    if missing:
        allow_missing = exception and _as_bool(policy.get("incident_exception_allows_missing_tests"), False)
        if allow_missing:
            _add(
                checks,
                blockers,
                reviews,
                PolicyCheck(
                    code="required_evidence",
                    outcome="human_review",
                    mandatory=False,
                    message="Required evidence missing; incident exception permits tests gap with human review.",
                    details={"missing": missing, "present": sorted(present)},
                ),
            )
        else:
            _add(
                checks,
                blockers,
                reviews,
                PolicyCheck(
                    code="required_evidence",
                    outcome="block",
                    mandatory=True,
                    message="Required test evidence is missing.",
                    details={"missing": missing, "required": required_evidence, "present": sorted(present)},
                ),
            )
    else:
        checks.append(
            PolicyCheck(
                code="required_evidence",
                outcome="pass",
                mandatory=True,
                message="Required evidence is present.",
                details={"required": required_evidence},
            )
        )

    blocked_without_simulation = set(_as_str_list(policy.get("blocked_without_simulation_for")))
    if req_type in blocked_without_simulation and not has_simulation_evidence(request, policy):
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="simulation_required",
                outcome="block",
                mandatory=True,
                message="Request type is blocked without passing simulation evidence.",
                details={"request_type": req_type, "evidence": sorted(present)},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="simulation_required",
                outcome="pass",
                mandatory=True,
                message="Simulation gate not applicable or satisfied.",
                details={"request_type": req_type},
            )
        )

    max_blast = policy.get("max_auto_approve_blast_radius")
    if max_blast is not None and blast_rank(request.get("blast_radius"), policy) > blast_rank(max_blast, policy):
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="blast_radius",
                outcome="human_review",
                mandatory=False,
                message="Blast radius exceeds the auto-approve ceiling.",
                details={
                    "blast_radius": request.get("blast_radius"),
                    "max_auto_approve_blast_radius": max_blast,
                },
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="blast_radius",
                outcome="pass",
                mandatory=False,
                message="Blast radius is within the auto-approve ceiling or no ceiling is configured.",
                details={"blast_radius": request.get("blast_radius"), "max_auto_approve_blast_radius": max_blast},
            )
        )

    if _as_bool(request.get("llm_generated"), False) and _as_bool(
        policy.get("llm_generated_changes_require_human_review"), False
    ):
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="ai_generated_change",
                outcome="human_review",
                mandatory=False,
                message="AI-generated changes require human review.",
                details={"llm_generated": True},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="ai_generated_change",
                outcome="pass",
                mandatory=False,
                message="AI-generation policy does not require review for this request.",
                details={"llm_generated": request.get("llm_generated")},
            )
        )

    risk = deterministic_risk(request, policy, context)
    if risk in {"high", "critical"}:
        _add(
            checks,
            blockers,
            reviews,
            PolicyCheck(
                code="deterministic_risk",
                outcome="human_review",
                mandatory=False,
                message="Deterministic risk is high enough to require human review.",
                details={"deterministic_risk": risk},
            ),
        )
    else:
        checks.append(
            PolicyCheck(
                code="deterministic_risk",
                outcome="pass",
                mandatory=False,
                message="Deterministic risk is within auto-approval band pending remaining gates.",
                details={"deterministic_risk": risk},
            )
        )

    # Deduplicate reason codes while preserving order.
    blockers = list(dict.fromkeys(blockers))
    reviews = [code for code in dict.fromkeys(reviews) if code not in blockers]

    return PolicyEvaluation(
        request_id=str(request.get("id", "")),
        request_hash=request_hash,
        policy_hash=policy_hash,
        context_hash=context_hash,
        deterministic_risk=risk,
        checks=checks,
        blockers=blockers,
        human_review_reasons=reviews,
        ingest_errors=ingest_list,
    )
