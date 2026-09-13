from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from control_plane.hashes import canonical_json, sha256_hex
from control_plane.models import VALID_CONFIDENCE, VALID_DECISIONS, VALID_RISK_LEVELS, LlmReview


LLM_SCHEMA_SPEC = {
    "risk_level": "one of low|medium|high|critical",
    "confidence": "one of low|medium|high",
    "recommendation": "one of auto_approve|human_review|block",
    "estimated_latency_impact_ms": "non-negative number",
    "reversibility": "one of high|medium|low",
    "testing_adequacy": "one of adequate|partial|insufficient",
    "justification_adequacy": "one of adequate|weak",
    "hidden_failure_modes": "array of short strings",
    "rationale": "short operational rationale",
}


def default_model() -> str:
    return os.getenv("CONTROL_PLANE_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.6-luna"


def build_prompt(
    request: dict[str, Any],
    policy: dict[str, Any],
    context: dict[str, Any],
    policy_evaluation: dict[str, Any],
) -> str:
    bounded = {
        "task": (
            "You are an advisory production-change reviewer. You do not authorize execution. "
            "Assess operational risk only. Deterministic policy already ran and remains authoritative."
        ),
        "request": {
            "id": request.get("id"),
            "title": request.get("title"),
            "request_type": request.get("request_type"),
            "service": request.get("service"),
            "environment": request.get("environment"),
            "summary": request.get("summary"),
            "proposed_change": request.get("proposed_change"),
            "blast_radius": request.get("blast_radius"),
            "rollback_defined": request.get("rollback_defined"),
            "test_evidence": request.get("test_evidence"),
            "change_window": request.get("change_window"),
            "llm_generated": request.get("llm_generated"),
        },
        "system_context": context,
        "policy_digest": {
            "protected_services": policy.get("protected_services"),
            "high_risk_request_types": policy.get("high_risk_request_types"),
            "latency_sensitive_services": policy.get("latency_sensitive_services"),
            "max_latency_impact_auto_approve_ms": policy.get("max_latency_impact_auto_approve_ms"),
            "max_auto_approve_blast_radius": policy.get("max_auto_approve_blast_radius"),
        },
        "deterministic_policy": {
            "deterministic_risk": policy_evaluation.get("deterministic_risk"),
            "blockers": policy_evaluation.get("blockers"),
            "human_review_reasons": policy_evaluation.get("human_review_reasons"),
        },
        "output_schema": LLM_SCHEMA_SPEC,
        "instructions": [
            "Return ONLY a JSON object matching output_schema.",
            "Do not invent missing evidence.",
            "If uncertainty is material, lower confidence and recommend human_review or block.",
            "estimated_latency_impact_ms must be a number, using 0 if no latency effect is expected.",
        ],
    }
    return canonical_json(bounded)


def _extract_json_object(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    stripped = text.strip()
    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    brace = re.search(r"\{.*\}", stripped, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, errors
        errors.append("json_root_not_object")
    errors.append("unparseable_json")
    return None, errors


def validate_llm_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    risk = str(payload.get("risk_level", "")).lower()
    confidence = str(payload.get("confidence", "")).lower()
    recommendation = str(payload.get("recommendation", "")).lower()
    if risk not in VALID_RISK_LEVELS:
        errors.append("invalid_risk_level")
    if confidence not in VALID_CONFIDENCE:
        errors.append("invalid_confidence")
    if recommendation not in VALID_DECISIONS:
        errors.append("invalid_recommendation")
    latency = payload.get("estimated_latency_impact_ms")
    latency_value: float | None
    try:
        latency_value = float(latency)
        if latency_value < 0:
            errors.append("negative_latency_impact")
            latency_value = None
    except (TypeError, ValueError):
        errors.append("invalid_latency_impact")
        latency_value = None
    modes = payload.get("hidden_failure_modes", [])
    if modes is None:
        modes = []
    if not isinstance(modes, list):
        errors.append("invalid_hidden_failure_modes")
        modes = []
    normalized = {
        "risk_level": risk if risk in VALID_RISK_LEVELS else None,
        "confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "recommendation": recommendation if recommendation in VALID_DECISIONS else None,
        "estimated_latency_impact_ms": latency_value,
        "reversibility": None if payload.get("reversibility") is None else str(payload.get("reversibility")),
        "testing_adequacy": None if payload.get("testing_adequacy") is None else str(payload.get("testing_adequacy")),
        "justification_adequacy": None
        if payload.get("justification_adequacy") is None
        else str(payload.get("justification_adequacy")),
        "hidden_failure_modes": [str(item) for item in modes],
        "rationale": str(payload.get("rationale") or ""),
    }
    return normalized, errors


class LlmCallLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    self.entries.append(json.loads(line))

    def find(self, prompt_hash: str, request_id: str, request_hash: str) -> dict[str, Any] | None:
        for entry in reversed(self.entries):
            if not entry.get("response_text"):
                continue
            if entry.get("prompt_hash") == prompt_hash:
                return entry
            if entry.get("request_id") == request_id and entry.get("request_hash") == request_hash:
                return entry
        return None

    def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _live_complete(prompt: str, model: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=prompt,
        store=True,
    )
    text = getattr(response, "output_text", None)
    if not text:
        raise RuntimeError("empty LLM response")
    return str(text)


def review_with_llm(
    request: dict[str, Any],
    policy: dict[str, Any],
    context: dict[str, Any],
    policy_evaluation: dict[str, Any],
    call_log: LlmCallLog,
    *,
    replay: bool,
    allow_live: bool,
) -> LlmReview:
    prompt = build_prompt(request, policy, context, policy_evaluation)
    prompt_hash = sha256_hex(prompt)
    request_id = str(request.get("id", ""))
    request_hash = policy_evaluation.get("request_hash") or sha256_hex(request)
    model = default_model()
    replayed = False
    raw_text = ""
    parse_errors: list[str] = []

    cached = call_log.find(prompt_hash, request_id, str(request_hash))
    if replay:
        if cached is None:
            parse_errors.append("replay_miss")
        else:
            raw_text = str(cached.get("response_text") or "")
            model = str(cached.get("model") or model)
            replayed = True
    elif cached is not None and cached.get("prompt_hash") == prompt_hash:
        raw_text = str(cached.get("response_text") or "")
        model = str(cached.get("model") or model)
        replayed = True
    elif not allow_live:
        parse_errors.append("live_llm_disabled")
    else:
        try:
            raw_text = _live_complete(prompt, model)
        except Exception as exc:  # noqa: BLE001 - fail closed with recorded reason
            parse_errors.append(f"llm_call_failed:{type(exc).__name__}")

    payload = None
    normalized: dict[str, Any] = {}
    if raw_text:
        payload, extract_errors = _extract_json_object(raw_text)
        parse_errors.extend(extract_errors)
        if payload is not None:
            normalized, schema_errors = validate_llm_payload(payload)
            parse_errors.extend(schema_errors)

    valid = bool(payload) and not parse_errors
    response_hash = sha256_hex(raw_text) if raw_text else ""
    if raw_text and not replayed:
        call_log.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "request_hash": request_hash,
                "prompt_hash": prompt_hash,
                "response_hash": response_hash,
                "model": model,
                "replayed": False,
                "valid": valid,
                "parse_errors": parse_errors,
                "prompt": prompt,
                "response_text": raw_text,
            }
        )
    elif replayed and cached is not None:
        call_log.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "request_hash": request_hash,
                "prompt_hash": prompt_hash,
                "response_hash": response_hash,
                "model": model,
                "replayed": True,
                "valid": valid,
                "parse_errors": parse_errors,
                "source_prompt_hash": cached.get("prompt_hash"),
            }
        )

    return LlmReview(
        request_id=request_id,
        valid=valid,
        replayed=replayed,
        model=model,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        risk_level=normalized.get("risk_level"),
        confidence=normalized.get("confidence"),
        recommendation=normalized.get("recommendation"),
        estimated_latency_impact_ms=normalized.get("estimated_latency_impact_ms"),
        reversibility=normalized.get("reversibility"),
        testing_adequacy=normalized.get("testing_adequacy"),
        justification_adequacy=normalized.get("justification_adequacy"),
        hidden_failure_modes=list(normalized.get("hidden_failure_modes") or []),
        rationale=str(normalized.get("rationale") or ""),
        parse_errors=parse_errors,
        raw_text=raw_text,
    )
