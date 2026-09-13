# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-101 | runtime_config_change | staging | human_review | human_review | no | FINALISED |

## Per-request rationale

### CR-101

- Evaluation: `800e8a2679477d3221394f369ef8c9ab12a587d4bc41ccfbc6d2a024a6b381f4`
- Request hash: `a5b6c8c2aa2576b8a4e799300255e00aec2793d0480f5b2e54da58fd588c508f`
- Deterministic risk: `low`
- LLM: valid=True replayed=False risk=high confidence=medium recommendation=human_review
- LLM rationale: The change is scoped and rollback is defined, but it affects protected pricing-edge during an active incident and high volatility. Increasing quote TTL may reduce backend pressure while increasing quote staleness; the provided test evidence lacks quantitative freshness and exposure results.
- System rationale:
  - llm_risk:high
  - llm_recommends_human_review
  - llm_justification_weak
- Human: action=pending reviewer=n/a binding_ok=True
- Execution: authorized=False result=skipped

