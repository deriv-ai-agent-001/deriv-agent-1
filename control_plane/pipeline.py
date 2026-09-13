from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from control_plane.artifacts import persist_artifacts
from control_plane.execution import authorize_and_execute
from control_plane.human import apply_human_review, load_human_reviews, matching_review
from control_plane.ingest import ingest_request, load_inputs
from control_plane.llm import LlmCallLog, review_with_llm
from control_plane.models import ChangeRecord
from control_plane.policy import evaluate_policy
from control_plane.reconcile import reconcile
from control_plane.states import State


@dataclass
class RunConfig:
    input_dir: Path
    output_dir: Path
    replay: bool = False
    execute: bool = False
    allow_live_llm: bool = True


def _policy_check(record: ChangeRecord, policy: dict, context: dict) -> None:
    record.machine.require(State.INGESTED)
    record.policy = evaluate_policy(
        record.original_request,
        policy,
        context,
        record.ingest_errors,
        record.request_hash,
        record.policy_hash,
        record.context_hash,
    )
    record.machine.enter(State.POLICY_CHECKED, "deterministic policy evaluation completed")


def _llm_review(record: ChangeRecord, policy: dict, context: dict, cfg: RunConfig, log: LlmCallLog) -> None:
    record.machine.require(State.POLICY_CHECKED)
    assert record.policy is not None
    record.llm = review_with_llm(
        record.original_request,
        policy,
        context,
        record.policy.to_dict(),
        log,
        replay=cfg.replay,
        allow_live=cfg.allow_live_llm,
    )
    record.machine.enter(State.LLM_REVIEWED, "advisory LLM review recorded and schema-validated")


def _reconcile_decision(record: ChangeRecord, policy: dict) -> None:
    record.machine.require(State.LLM_REVIEWED)
    reconcile(record, policy)
    record.machine.enter(State.DECISION_RECONCILED, "policy and LLM outputs reconciled; policy remains authoritative")


def evaluate_record(
    record: ChangeRecord,
    policy: dict,
    context: dict,
    cfg: RunConfig,
    log: LlmCallLog,
    human_reviews: list[dict],
) -> ChangeRecord:
    _policy_check(record, policy, context)
    _llm_review(record, policy, context, cfg, log)
    _reconcile_decision(record, policy)

    if record.system_recommendation == "human_review":
        record.machine.enter(State.HUMAN_REVIEW_REQUIRED, "system recommendation requires a human decision")
        apply_human_review(record, matching_review(record, human_reviews))
        human = record.human
        if human and human.action == "request_evidence":
            record.machine.enter(State.FINALISED, "human requested additional evidence; not executable")
            record.executable = False
            return record
        record.machine.enter(State.FINALISED, "human outcome recorded without overwriting machine recommendation")
    else:
        if record.system_recommendation == "auto_approve":
            record.executable = True
            record.closed_reason = "auto_approved"
        else:
            record.executable = False
            record.closed_reason = "blocked"
        record.machine.enter(State.FINALISED, "terminal decision persisted")
    return record


def run(cfg: RunConfig) -> list[ChangeRecord]:
    requests, policy, context = load_inputs(cfg.input_dir)
    human_reviews = load_human_reviews(cfg.input_dir)
    log = LlmCallLog(cfg.output_dir / "llm_calls.jsonl")
    records: list[ChangeRecord] = []
    occupied: set[str] = set()

    for payload in requests:
        record = ingest_request(payload, policy, context)
        evaluate_record(record, policy, context, cfg, log, human_reviews)
        authorize_and_execute(record, policy, context, occupied_services=occupied, execute=cfg.execute)
        records.append(record)

    persist_artifacts(cfg.output_dir, records)
    return records
