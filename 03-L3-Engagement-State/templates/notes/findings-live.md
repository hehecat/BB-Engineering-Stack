# Findings Live Log

Internal states: `candidate`, `confirmed`, `packaged`, `submitted`, `closed`.
Internal `F-*` IDs must not leak into reviewer-facing deliverables.

| ID | State | Title | Asset | Impact reached | Evidence | Next action |
| --- | --- | --- | --- | --- | --- | --- |

## Entry Template

### F-001: Descriptive internal title

- State: candidate
- Related hypotheses: H-001
- Asset and endpoint: exact in-scope surface
- Identity context: stable label or unauthenticated
- Primitive: observable behavior proven
- Impact reached: concrete current impact
- Reproduction delta: baseline versus modified request
- Evidence: relative paths under `artifacts/` or `recon/`
- Scope check: applicable rule and scope revision
- Chain status: standalone, partial chain, or chained
- Cleanup: completed, unnecessary, or exact remaining action
- Next action: prove, close, validate, or package
