# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-102 | risk_rule_change | production | block | block | no | FINALISED |

## Per-request rationale

### CR-102

- Evaluation: `54aa425de8da01076e1800c28b951222612a7d55249c289e67816b406620ee06`
- Request hash: `e354c74e20ff2a6da81c6346a69d45c4571417b22303a47374b262b6c510efcc`
- Deterministic risk: `critical`
- Mandatory blockers: required_evidence, simulation_required
- Human-review conditions: protected_service, high_risk_request_type, blast_radius, ai_generated_change, deterministic_risk
- LLM: valid=True replayed=False risk=critical confidence=high recommendation=block
- LLM rationale: Block because this is an AI-generated, high-risk production risk-rule change affecting a protected service across multiple regions during an incident and high volatility, with only partial simulation evidence and insufficient required evidence.
- System rationale:
  - mandatory_policy_blocker:required_evidence
  - mandatory_policy_blocker:simulation_required
  - llm_recommends_block
  - llm_risk:critical
  - llm_testing_inadequate
  - llm_justification_weak
  - policy_human_review:protected_service
  - policy_human_review:high_risk_request_type
  - policy_human_review:blast_radius
  - policy_human_review:ai_generated_change
  - policy_human_review:deterministic_risk
- Execution: authorized=False result=skipped

