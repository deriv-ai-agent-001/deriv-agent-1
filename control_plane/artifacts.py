from __future__ import annotations

from pathlib import Path
from typing import Any

from control_plane.hashes import canonical_json
from control_plane.models import ChangeRecord


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def persist_artifacts(output_dir: Path, records: list[ChangeRecord]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy_evaluations = [r.policy.to_dict() if r.policy else {"request_id": r.request_id, "missing": True} for r in records]
    llm_reviews = [r.llm.to_dict() if r.llm else {"request_id": r.request_id, "missing": True} for r in records]
    finals = [r.to_final_dict() for r in records]
    write_json(output_dir / "policy_evaluation.json", policy_evaluations)
    write_json(output_dir / "llm_reviews.json", llm_reviews)
    write_json(output_dir / "final_decisions.json", finals)
    (output_dir / "decision_summary.md").write_text(render_summary(records), encoding="utf-8")


def render_summary(records: list[ChangeRecord]) -> str:
    lines = [
        "# Decision summary",
        "",
        "Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.",
        "",
        "| Request | Type | Env | Machine | Final | Executable | State |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        req = record.original_request
        lines.append(
            "| {id} | {typ} | {env} | {machine} | {final} | {exe} | {state} |".format(
                id=record.request_id,
                typ=req.get("request_type", ""),
                env=req.get("environment", ""),
                machine=record.system_recommendation or "",
                final=record.final_decision or "",
                exe="yes" if record.executable else "no",
                state="" if record.state is None else record.state.value,
            )
        )
    lines.extend(["", "## Per-request rationale", ""])
    for record in records:
        lines.append(f"### {record.request_id}")
        lines.append("")
        lines.append(f"- Evaluation: `{record.evaluation_id}`")
        lines.append(f"- Request hash: `{record.request_hash}`")
        if record.policy:
            lines.append(f"- Deterministic risk: `{record.policy.deterministic_risk}`")
            if record.policy.blockers:
                lines.append(f"- Mandatory blockers: {', '.join(record.policy.blockers)}")
            if record.policy.human_review_reasons:
                lines.append(f"- Human-review conditions: {', '.join(record.policy.human_review_reasons)}")
        if record.llm:
            lines.append(
                f"- LLM: valid={record.llm.valid} replayed={record.llm.replayed} "
                f"risk={record.llm.risk_level} confidence={record.llm.confidence} "
                f"recommendation={record.llm.recommendation}"
            )
            if record.llm.rationale:
                lines.append(f"- LLM rationale: {record.llm.rationale}")
        if record.system_rationale:
            lines.append("- System rationale:")
            for reason in record.system_rationale:
                lines.append(f"  - {reason}")
        if record.human:
            lines.append(
                f"- Human: action={record.human.action} reviewer={record.human.reviewer or 'n/a'} "
                f"binding_ok={record.human.binding_ok}"
            )
        if record.execution:
            lines.append(
                f"- Execution: authorized={record.execution.authorized} result={record.execution.result}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"
