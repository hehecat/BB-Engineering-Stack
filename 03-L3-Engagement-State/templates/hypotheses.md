# Hypotheses

Internal states: `queued`, `active`, `validated`, `killed`, `deferred`.

| ID | State | Scope | Class | Surface | Signal | Identity | Evidence | Exact next test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Entry Template

### H-001: Descriptive hypothesis

- State: queued
- Asset state: active, candidate, or deferred
- Surface: endpoint, page, component, or file
- Class: vulnerability or challenge class
- Signal: observation that justifies the hypothesis
- Soft rank: trust-boundary and impact signal minus time and side effects
- Identity context: unauthenticated or a stable label from `engagement.yaml`
- Baseline: expected/control behavior
- Test: one concrete differentiating action
- Planned side effects: exact action and remaining Scope budget
- Result: not tested
- Evidence: no evidence yet
- Conclusion: open
- Next action: execute the differentiating test
