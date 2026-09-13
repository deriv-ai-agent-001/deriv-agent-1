# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-101 | runtime_config_change | staging | human_review | human_review | no | FINALISED |
| CR-102 | risk_rule_change | production | block | block | no | FINALISED |
| CR-103 | code_deployment | production | block | block | no | FINALISED |
| CR-104 | prompt_change | production | human_review | human_review | no | FINALISED |

## Per-request rationale

### CR-101

- Evaluation: `800e8a2679477d3221394f369ef8c9ab12a587d4bc41ccfbc6d2a024a6b381f4`
- Request hash: `a5b6c8c2aa2576b8a4e799300255e00aec2793d0480f5b2e54da58fd588c508f`
- Deterministic risk: `low`
- LLM: valid=True replayed=True risk=high confidence=medium recommendation=human_review
- LLM rationale: Although reversible and tested in staging, increasing TTL on protected pricing-edge during an active incident and high volatility may increase quote staleness and exposure; evidence lacks production-like staleness and safety measurements.
- System rationale:
  - llm_risk:high
  - llm_recommends_human_review
  - llm_justification_weak
- Human: action=pending reviewer=n/a binding_ok=True
- Execution: authorized=False result=skipped

### CR-102

- Evaluation: `54aa425de8da01076e1800c28b951222612a7d55249c289e67816b406620ee06`
- Request hash: `e354c74e20ff2a6da81c6346a69d45c4571417b22303a47374b262b6c510efcc`
- Deterministic risk: `critical`
- Mandatory blockers: required_evidence, simulation_required
- Human-review conditions: protected_service, high_risk_request_type, blast_radius, ai_generated_change, deterministic_risk
- LLM: valid=True replayed=True risk=critical confidence=high recommendation=block
- LLM rationale: Block: this is an AI-generated high-risk production risk-rule change affecting a protected service across multiple regions during an active incident and high volatility. Required evidence and complete simulation are missing, and the change increases exposure contrary to executive guidance.
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

### CR-103

- Evaluation: `4b330494f252c4bb64ab2f4ce0d3761e502ed45e71c676f2042e5bee6be57031`
- Request hash: `863280c10557bbf179cdb99cecc8662e8e44c82aa5123515e7a6b0c1ebb1a45c`
- Deterministic risk: `critical`
- Mandatory blockers: rollback_required
- Human-review conditions: blast_radius, deterministic_risk
- LLM: valid=True replayed=True risk=critical confidence=low recommendation=block
- LLM rationale: Global production deployment during an active high-volatility incident lacks a defined rollback and has only unit-test evidence; deterministic policy requires blocking.
- System rationale:
  - mandatory_policy_blocker:rollback_required
  - llm_recommends_block
  - llm_risk:critical
  - llm_confidence_low
  - llm_testing_inadequate
  - llm_justification_weak
  - policy_human_review:blast_radius
  - policy_human_review:deterministic_risk
- Execution: authorized=False result=skipped

### CR-104

- Evaluation: `a708165e139e25ba98c82ade3ff58a1481b185586c798b23d454afc0ac8b679d`
- Request hash: `6fab697a7336037e9a99f8d34f98d69b00f79e8a5db4b964e39a1f5258a023f2`
- Deterministic risk: `high`
- Human-review conditions: ai_generated_change, deterministic_risk
- LLM: valid=True replayed=True risk=high confidence=high recommendation=human_review
- LLM rationale: The change is reversible and limited to an internal assistant, with no expected latency impact, but it is an AI-generated production prompt change supported only by an unspecified offline evaluation during an active high-volatility incident.
- System rationale:
  - llm_risk:high
  - llm_recommends_human_review
  - llm_justification_weak
  - policy_human_review:ai_generated_change
  - policy_human_review:deterministic_risk
- Human: action=pending reviewer=n/a binding_ok=True
- Execution: authorized=False result=skipped

