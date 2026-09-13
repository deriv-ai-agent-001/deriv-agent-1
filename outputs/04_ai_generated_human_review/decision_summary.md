# Decision summary

Fail-closed control plane. Deterministic policy is authoritative; LLM output is advisory.

| Request | Type | Env | Machine | Final | Executable | State |
|---|---|---|---|---|---|---|
| CR-104 | prompt_change | production | human_review | human_review | no | FINALISED |

## Per-request rationale

### CR-104

- Evaluation: `a708165e139e25ba98c82ade3ff58a1481b185586c798b23d454afc0ac8b679d`
- Request hash: `6fab697a7336037e9a99f8d34f98d69b00f79e8a5db4b964e39a1f5258a023f2`
- Deterministic risk: `high`
- Human-review conditions: ai_generated_change, deterministic_risk
- LLM: valid=True replayed=False risk=high confidence=medium recommendation=human_review
- LLM rationale: Production prompt change is reversible and limited to one internal service, but it is AI-generated, supported only by offline evaluation, and proposed during an active incident with high market volatility.
- System rationale:
  - llm_risk:high
  - llm_recommends_human_review
  - llm_justification_weak
  - policy_human_review:ai_generated_change
  - policy_human_review:deterministic_risk
- Human: action=pending reviewer=n/a binding_ok=True
- Execution: authorized=False result=skipped

