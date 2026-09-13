# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-103 | code_deployment | production | block | block | no | FINALISED |

## Per-request rationale

### CR-103

- Evaluation: `4b330494f252c4bb64ab2f4ce0d3761e502ed45e71c676f2042e5bee6be57031`
- Request hash: `863280c10557bbf179cdb99cecc8662e8e44c82aa5123515e7a6b0c1ebb1a45c`
- Deterministic risk: `critical`
- Mandatory blockers: rollback_required
- Human-review conditions: blast_radius, deterministic_risk
- LLM: valid=True replayed=False risk=critical confidence=high recommendation=block
- LLM rationale: Block: deterministic rollback blocker applies, while this global production change affects a latency-sensitive protected service during an incident and has only unit-test evidence.
- System rationale:
  - mandatory_policy_blocker:rollback_required
  - llm_recommends_block
  - llm_risk:critical
  - llm_testing_inadequate
  - llm_justification_weak
  - policy_human_review:blast_radius
  - policy_human_review:deterministic_risk
- Execution: authorized=False result=skipped

