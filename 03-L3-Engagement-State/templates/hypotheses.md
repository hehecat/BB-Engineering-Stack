# Hypotheses

Internal states: `queued`, `active`, `validated`, `killed`, `deferred`.

| ID | State | Class | Surface | Signal | Identity | Evidence | Exact next test |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Entry Template

### H-001: Descriptive hypothesis

- State: queued
- Surface: endpoint, page, component, or file
- Class: vulnerability or challenge class
- Signal: observation that justifies the hypothesis
- Identity context: unauthenticated or a stable label from `engagement.yaml`
- Baseline: expected/control behavior
- Test: one concrete differentiating action
- Result: not tested
- Evidence: no evidence yet
- Conclusion: open
- Next action: execute the differentiating test
