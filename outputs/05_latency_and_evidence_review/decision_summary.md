# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-105 | runtime_config_change | production | block | block | no | FINALISED |

## Per-request rationale

### CR-105

- Evaluation: `446001519a9eb56ba0d4d0f2eea63cfe3621266d164bc9d27a85e0aafa4452c0`
- Request hash: `990b8e1a2f8e8b12f4b69e32a9fd4223f3904cb096bf57b5801352747fd4f9aa`
- Deterministic risk: `high`
- Mandatory blockers: required_evidence
- Human-review conditions: protected_service, deterministic_risk
- LLM: valid=True replayed=False risk=critical confidence=high recommendation=block
- LLM rationale: The change affects protected pricing-edge during an incident and high market volatility; available evidence only covers load performance, not quote freshness, correctness, or exposure controls.
- System rationale:
  - mandatory_policy_blocker:required_evidence
  - llm_recommends_block
  - llm_risk:critical
  - llm_testing_inadequate
  - llm_justification_weak
  - policy_human_review:protected_service
  - policy_human_review:deterministic_risk
- Execution: authorized=False result=skipped

