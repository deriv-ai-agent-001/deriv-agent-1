## ARCHITECTURE

The gateway is designed as a fail-closed, replayable control plane where deterministic policy is authoritative, the LLM provides advisory risk analysis, human approval resolves governed ambiguity, and execution is independently guarded by runtime safety checks.

Input Files
  ├── change_requests.json
  ├── policy_config.json
  └── system_context.json
          │
          ▼
1. INGESTED
   - Load and validate inputs
   - Preserve original request payload
   - Assign request/evaluation identifiers
          │
          ▼
2. POLICY_CHECKED
   - Run deterministic policy checks:
     environment, request type, protected service,
     rollback, evidence, incident exception,
     blast radius, AI-generated
   - Derive deterministic risk
   - Record blockers and human-review conditions
   - Mandatory policy failures cannot be overridden
          │
          ▼
3. LLM_REVIEWED
   - Send bounded request + policy/context to LLM
   - Assess operational risk, hidden failure modes,
     latency, reversibility, testing, and justification
   - Validate strict structured JSON response
   - LLM output remains advisory
          │
          ▼
4. DECISION_RECONCILED
   - Reconcile deterministic policy + LLM assessment
   - Precedence: BLOCK > HUMAN_REVIEW > AUTO_APPROVE
   - High/critical risk or low confidence escalates
   - AI-generated changes follow configured approval policy
   - Produce system recommendation + rationale
          │
          ├──────────────► human_review
          │                    │
          │                    ▼
          │              5. HUMAN_REVIEW_REQUIRED
          │                 - approve with justification
          │                 - reject with justification
          │                 - request additional evidence
          │                 - never overwrite machine recommendation
          │                    │
          │                    └── evidence change → re-evaluate
          │
          ▼
6. FINALISED
   - Persist final system decision
   - Preserve human outcome where applicable
   - `executable=true` only after all required gates pass
          │
          ▼
7. EXECUTION CONTROL
   - Revalidate policy/context/request versions
   - Check approval expiry and concurrency
   - Verify rollback plan/readiness
   - Verify blast radius and execution preconditions
   - Persist execution authorization
          │
          ▼
8. EXECUTE
   - Prepare / snapshot
   - Canary where required
   - Execute change
   - Verify post-change health
          │
       ┌──┴─────────┐
       │            │
    SUCCESS       FAILURE
       │            │
       ▼            ▼
    VERIFIED   ROLLBACK_PENDING
                    │
                    ▼
              ROLLING_BACK
                 /      \
                /        \
        ROLLED_BACK   ROLLBACK_FAILED
                         │
                         ▼
                   Incident escalation


## CORE SAFETY INVARIANTS

• No AUTO_APPROVE before POLICY_CHECKED and LLM_REVIEWED.
• Mandatory deterministic blockers always result in BLOCK.
• LLM output can escalate a decision but cannot bypass mandatory policy.
• HUMAN_REVIEW and BLOCK are never executable without the required subsequent authorization.
• Execution performs a fresh precondition check; approval is not permanent.
• Human approval is bound to the exact request/version/context and may expire.
• Production changes requiring rollback cannot execute without a verified rollback plan.
• Failed rollback transitions to an explicit ROLLBACK_FAILED state and triggers escalation.
• Every state transition, policy result, LLM result, human outcome, and execution result is auditable.
• Replay uses the recorded LLM response rather than invoking a new live model.

## DECISION MODEL
Mandatory policy blocker        → BLOCK
Mandatory condition unresolved  → BLOCK
Required human approval         → HUMAN_REVIEW
LLM risk = HIGH/CRITICAL        → HUMAN_REVIEW
LLM confidence = LOW            → HUMAN_REVIEW
LLM recommends BLOCK            → BLOCK
All mandatory gates pass
+ LLM review completed
+ sufficient confidence
+ no escalation condition      → AUTO_APPROVE


## PERSISTED ARTIFACTS
outputs/
├── policy_evaluation.json
├── llm_reviews.json
├── final_decisions.json
├── decision_summary.md
└── llm_calls.jsonl

``final_decisions.json`` is the canonical audit artifact and preserves the original request, deterministic policy evaluation, LLM review, reconciled decision, human outcome, execution eligibility, and ordered stage history.

## RUNNING THE PROTOTYPE

```text
pip install -r requirements.txt
python -m control_plane
python -m control_plane --replay
python -m control_plane --replay --execute
python -m unittest
```

Optional `input/human_reviews.json` binds approve / reject / request_evidence to the exact request (and optional policy/context) hashes. Human approval cannot override a mandatory BLOCK.

`--replay` reuses `outputs/llm_calls.jsonl`. Without a recorded or live LLM response the pipeline fails closed to `block`. Set `OPENAI_API_KEY` for a live advisory review (model `gpt-5.6-luna` by default).


## FINAL SUBMISSION REPORT

See docs/AI_Operations_Gateway_Final_Submission_Report.pdf for the architecture, control flow, live validation results, audit/replay approach, safety properties, and remaining hardening items.

The live validation covered CR-101 (human_review, non-executable) and CR-105 (block, non-executable). The corresponding run artifacts should be retained under the run-specific outputs/ directory.

Required artifacts generated by the control plane:
- policy_evaluation.json
- llm_reviews.json
- final_decisions.json
- decision_summary.md
- llm_calls.jsonl

#### Validation Scores
A. Run 01 - Baseline Auto Approve Change (CR-101): 82-85%. 
Live end-to-end processing, deterministic policy, LLM review, reconciliation and non-executable human-review outcome were demonstrated. Remaining gaps were exact LLM schema alignment and independent latency-budget validation.

B. Run 05 - Latency & Evidence Review (CR-105): 88%. 
Mandatory evidence blocking, protected-service handling, critical LLM assessment, reconciliation and execution gating were demonstrated. A dedicated latency-only test remains the principal validation gap.