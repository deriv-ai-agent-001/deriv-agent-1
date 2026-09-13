from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from control_plane.models import DEFAULT_BLAST_RADIUS_ORDER


class ConfigError(ValueError):
    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def generate_run_id(explicit: str | None = None) -> str:
    if explicit:
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", explicit).strip("._-")
        if cleaned:
            return cleaned
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{uuid.uuid4().hex[:8]}"


def unique_run_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    suffix = uuid.uuid4().hex[:6]
    candidate = f"{base}_{suffix}"
    while candidate in existing:
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
    return candidate


def _expect_list(policy: dict[str, Any], key: str, errors: list[str]) -> None:
    if key in policy and not isinstance(policy[key], list):
        errors.append(f"policy.{key}_must_be_array")


def _expect_bool(policy: dict[str, Any], key: str, errors: list[str]) -> None:
    if key in policy and not isinstance(policy[key], bool):
        errors.append(f"policy.{key}_must_be_boolean")


def validate_policy_config(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _expect_list(policy, "protected_services", errors)
    _expect_list(policy, "high_risk_request_types", errors)
    _expect_list(policy, "blocked_without_simulation_for", errors)
    _expect_list(policy, "latency_sensitive_services", errors)
    _expect_list(policy, "blast_radius_order", errors)
    _expect_bool(policy, "production_requires_rollback", errors)
    _expect_bool(policy, "incident_exception_allows_missing_tests", errors)
    _expect_bool(policy, "incident_exception_allows_missing_rollback", errors)
    _expect_bool(policy, "llm_generated_changes_require_human_review", errors)
    _expect_bool(policy, "llm_generated_changes_auto_approve", errors)

    evidence = policy.get("required_evidence_by_type")
    if evidence is not None and not isinstance(evidence, dict):
        errors.append("policy.required_evidence_by_type_must_be_object")
    elif isinstance(evidence, dict):
        for key, value in evidence.items():
            if not isinstance(value, list):
                errors.append(f"policy.required_evidence_by_type.{key}_must_be_array")

    latency = policy.get("max_latency_impact_auto_approve_ms")
    if latency is not None:
        try:
            if float(latency) < 0:
                errors.append("policy.max_latency_impact_auto_approve_ms_negative")
        except (TypeError, ValueError):
            errors.append("policy.max_latency_impact_auto_approve_ms_invalid")

    ttl = policy.get("approval_ttl_seconds")
    if ttl is not None:
        try:
            if float(ttl) < 0:
                errors.append("policy.approval_ttl_seconds_negative")
        except (TypeError, ValueError):
            errors.append("policy.approval_ttl_seconds_invalid")

    order = policy.get("blast_radius_order")
    ranks = [str(item) for item in order] if isinstance(order, list) and order else list(DEFAULT_BLAST_RADIUS_ORDER)
    max_blast = policy.get("max_auto_approve_blast_radius")
    if max_blast is not None and str(max_blast) not in ranks:
        errors.append("policy.max_auto_approve_blast_radius_not_in_order")

    if policy.get("llm_generated_changes_require_human_review") is True and policy.get(
        "llm_generated_changes_auto_approve"
    ) is True:
        errors.append("policy.contradictory_ai_generated_approval")

    if policy.get("production_requires_rollback") is True and policy.get("forbid_rollback_plans") is True:
        errors.append("policy.contradictory_rollback_settings")

    sensitive = policy.get("latency_sensitive_services")
    if isinstance(sensitive, list) and sensitive and latency is None:
        errors.append("policy.latency_sensitive_services_missing_budget")

    return errors
