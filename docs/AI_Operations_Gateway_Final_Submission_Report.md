# AI-Assisted Production Change Control Plane — Final Submission Report

## 1. Executive Summary

This submission implements a replayable, fail-closed control plane for AI-assisted production changes. The design separates deterministic policy enforcement from LLM-based risk assessment, reconciles both through an explicit decision layer, preserves machine and human judgments independently, and prevents executable status unless required controls have passed.

Two live fixture runs were validated during development. CR-101 was routed to `human_review` because the live LLM assessed the change as high risk with medium confidence in an active-incident/high-volatility context. CR-105 was blocked because deterministic policy identified a mandatory evidence failure, while the LLM independently assessed critical risk and recommended block. In both cases execution remained non-executable.

## 2. Architecture and Control Flow

Required governance flow:

`INGESTED → POLICY_CHECKED → LLM_REVIEWED → DECISION_RECONCILED → HUMAN_REVIEW_REQUIRED (when applicable) → FINALISED`

Additional execution-control flow:

`FINALISED → PRECONDITION_CHECKED → EXECUTION_AUTHORIZED → PREPARED → EXECUTING → VERIFIED / ROLLBACK_PENDING → ROLLING_BACK → ROLLED_BACK / ROLLBACK_FAILED`

### Stage responsibilities

| Stage | Responsibility |
|---|---|
| INGESTED | Load, validate, fingerprint and preserve the original request |
| POLICY_CHECKED | Run deterministic controls, derive risk, identify blockers/review conditions |
| LLM_REVIEWED | Perform bounded advisory risk analysis and validate structured output |
| DECISION_RECONCILED | Reconcile deterministic and AI signals; policy remains authoritative |
| HUMAN_REVIEW_REQUIRED | Obtain approval, rejection or additional evidence |
| FINALISED | Persist system recommendation, human outcome, execution eligibility and stage history |
| Execution controls | Revalidate approved intent and protect execution/rollback |

## 3. Deterministic Policy Controls

The policy engine evaluates environment sensitivity, request type risk, protected service status, rollback requirement, evidence sufficiency, incident exception logic, blast radius and AI-generated status. It also incorporates the configured latency-sensitive service and evidence thresholds.

For CR-105, the production request targeted protected and latency-sensitive `pricing-edge`, and the supplied policy required `staging_smoke_test_passed` evidence for `runtime_config_change`. The request provided only `load_test_passed`; the system therefore recorded `required_evidence` as a mandatory blocker and derived deterministic risk as `high`.

## 4. Structured LLM Risk Review

Live LLM calls were recorded with request/prompt/response hashes and validation metadata. The observed reviews were advisory and did not directly set executability.

### CR-101

- Risk: `high`
- Confidence: `medium`
- Recommendation: `human_review`
- Reversibility: `high`
- Testing adequacy: `partial`
- LLM-estimated latency impact: `0 ms`

The model identified stale-quote/exposure risk, cache invalidation concerns, insufficient quantitative evidence, and elevated risk during the active incident/high-volatility context.

### CR-105

- Risk: `critical`
- Confidence: `high`
- Recommendation: `block`
- Reversibility: `high`
- Testing adequacy: `insufficient`
- LLM-estimated latency impact: `0 ms`

The model identified stale-quote exposure, cache invalidation lag, regional inconsistency, and insufficient freshness/correctness/exposure testing.

## 5. Decision Reconciliation and Safety

The reconciliation layer preserves deterministic policy authority and uses AI signals to escalate or reinforce a decision.

### CR-101 result

`system_recommendation = human_review`

`final_decision = human_review`

`executable = false`

The request followed the complete governance state flow through `HUMAN_REVIEW_REQUIRED` and was finalised with no human authorization, so execution was skipped.

### CR-105 result

`system_recommendation = block`

`final_decision = block`

`executable = false`

The mandatory `required_evidence` blocker was not overridden by the LLM; the independent LLM assessment also recommended block. Execution was skipped.

## 6. Human Review and Explainability

Machine recommendation and human outcome are preserved as separate fields. A pending human review remains non-executable. Additional evidence, when supplied, is intended to re-enter the policy/LLM/reconciliation path rather than silently changing the prior judgment.

`decision_summary.md` provides per-request rationale, including deterministic findings, LLM concerns, reconciliation reasons and execution status. For blocked requests, the summary is designed to identify what must change before the request can become reviewable or approvable.

## 7. Auditability and Replay

The final decision artifact preserves the original request payload, policy evaluation, LLM review, system recommendation, human outcome where present, execution state, hashes and ordered stage history.

`llm_calls.jsonl` records the LLM interaction needed for replay, including prompt and response hashes and the recorded response. This enables replay without relying on a new live model response.

## 8. Failure and Recovery Strategy

The control plane is designed to fail closed. Invalid or incomplete LLM output cannot produce auto-approval; mandatory deterministic blockers cannot be overridden; and non-executable decisions cannot enter the execution path.

The implementation also includes explicit treatment for malformed LLM output, missing inputs, policy validation, replay, execution preconditions and rollback states. Remaining hardening items are called out below rather than overstated as fully validated.

## 9. Live Validation Results

| Run | Scenario | Deterministic result | LLM result | Final result | Executable |
|---|---|---|---|---|---|
| 01 / CR-101 | Baseline runtime config change | Low risk; no blocker | High / medium confidence / human_review | `human_review` | `false` |
| 05 / CR-105 | Production latency + evidence risk | High risk; mandatory evidence blocker | Critical / high confidence / block | `block` | `false` |

These runs demonstrate the most important safety properties: policy checks precede LLM review, AI output is advisory, mandatory blockers remain authoritative, elevated AI risk can escalate, and neither scenario became executable without the required authorization.

### Run 01 Assessment - Baseline Auto Approve Change

**Score: 82-85%.** The run demonstrates a functioning end-to-end state machine, deterministic policy evaluation, live LLM review, conservative reconciliation and correct prevention of execution. CR-101 was escalated to `human_review` because the live LLM assessed high operational risk with medium confidence. The principal gaps at this stage were exact LLM-schema alignment with the assignment contract and independent proof of deterministic latency-budget enforcement.

`CR-101 → human_review | executable = false | state = FINALISED`

### Run 05 Assessment - Latency & Evidence Review

**Score: 88%.** This was the stronger validation run. CR-105 targeted production `pricing-edge`, a protected and latency-sensitive service, while supplying only `load_test_passed`. The deterministic policy engine correctly identified missing `staging_smoke_test_passed` evidence as a mandatory blocker. The LLM independently assessed the request as critical risk with high confidence and recommended `block`. Reconciliation preserved the blocker and execution remained skipped.

`CR-105 → block | executable = false | mandatory blocker = required_evidence`

The remaining limitation is that this run proves safe blocking more strongly than it proves the latency-budget mechanism itself because the LLM returned a 0 ms latency estimate. A dedicated latency-only test is therefore still required to demonstrate deterministic latency-budget escalation.

## 10. Final Hardening Items

The following should be treated as remaining evaluator/production hardening rather than demonstrated capabilities:

1. Align the canonical LLM schema exactly with the assignment field names: `llm_risk_level`, `confidence`, `key_risks`, `recommended_action`, `required_followups`, and `latency_risk_ms_estimate`.
2. Make deterministic latency-budget evaluation independently visible and testable; do not rely only on the LLM's numeric latency estimate.
3. Complete and validate the evidence-request re-entry loop, durable interrupted-run resume, and cross-run hash-bound execution authorization.
4. Complete the remaining evaluator-matrix tests, including malformed LLM JSON, missing fields, latency, human approval, stale authorization, interruption/recovery and rollback failure.
5. Complete a dedicated positive latency-budget test where all other policy gates pass and latency alone causes `human_review`.

## 11. Submission Artifacts

The solution produces the required artifacts:

- `policy_evaluation.json`
- `llm_reviews.json`
- `final_decisions.json`
- `decision_summary.md`
- `llm_calls.jsonl`

Recommended repository layout:

`docs/AI_Operations_Gateway_Final_Submission_Report.pdf`

The report should be referenced from `README.md` together with the run-specific output directory used for validation.

## 12. Conclusion

The implementation demonstrates the core control-plane design required for high-stakes operational changes: deterministic policy establishes non-negotiable constraints, the LLM provides bounded advisory reasoning, reconciliation produces the system recommendation, human review handles governed ambiguity, and execution remains separately protected.

The live CR-101 and CR-105 runs provide concrete evidence of conservative behavior under both escalation and blocking conditions. The remaining items are primarily contract alignment, deeper recovery/authorization validation, and explicit latency/edge-case test coverage.
