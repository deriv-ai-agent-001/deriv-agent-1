from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from control_plane.hashes import sha256_hex
from control_plane.models import REQUIRED_REQUEST_FIELDS, ChangeRecord, request_id_of
from control_plane.states import State, StateMachine


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_inputs(input_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    requests_raw = load_json(input_dir / "change_requests.json")
    policy = load_json(input_dir / "policy_config.json")
    context = load_json(input_dir / "system_context.json")
    if not isinstance(policy, dict):
        raise ValueError("policy_config.json must be a JSON object")
    if not isinstance(context, dict):
        raise ValueError("system_context.json must be a JSON object")
    if not isinstance(requests_raw, list):
        raise ValueError("change_requests.json must be a JSON array")
    requests: list[dict[str, Any]] = []
    for item in requests_raw:
        if not isinstance(item, dict):
            raise ValueError("each change request must be a JSON object")
        requests.append(item)
    return requests, policy, context


def validate_request(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_REQUEST_FIELDS:
        if field not in payload:
            errors.append(f"missing_field:{field}")
    if "rollback_defined" in payload and not isinstance(payload["rollback_defined"], bool):
        errors.append("invalid_type:rollback_defined")
    if "llm_generated" in payload and not isinstance(payload["llm_generated"], bool):
        errors.append("invalid_type:llm_generated")
    if "test_evidence" in payload and not isinstance(payload["test_evidence"], list):
        errors.append("invalid_type:test_evidence")
    if "proposed_change" in payload and not isinstance(payload["proposed_change"], dict):
        errors.append("invalid_type:proposed_change")
    if "id" in payload and payload["id"] in (None, ""):
        errors.append("empty_id")
    return errors


def ingest_request(
    payload: dict[str, Any],
    policy: dict[str, Any],
    context: dict[str, Any],
) -> ChangeRecord:
    original = json.loads(json.dumps(payload))
    req_id = request_id_of(original)
    request_hash = sha256_hex(original)
    policy_hash = sha256_hex(policy)
    context_hash = sha256_hex(context)
    evaluation_id = sha256_hex(
        {
            "request_id": req_id,
            "request_hash": request_hash,
            "policy_hash": policy_hash,
            "context_hash": context_hash,
        }
    )
    machine = StateMachine()
    record = ChangeRecord(
        original_request=original,
        request_id=req_id,
        evaluation_id=evaluation_id,
        request_hash=request_hash,
        policy_hash=policy_hash,
        context_hash=context_hash,
        machine=machine,
        ingest_errors=validate_request(original),
    )
    machine.enter(State.INGESTED, "loaded and fingerprinted original request payload")
    return record
