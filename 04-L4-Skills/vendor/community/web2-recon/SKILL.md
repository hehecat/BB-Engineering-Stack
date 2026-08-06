---
name: web2-recon
description: Use when Web2 reconnaissance needs an adaptive idea beyond the standard Engagement baseline.
---

# Web2 Recon Reference

Use this Skill as a hypothesis source under `bb-orchestrator`. Use `bb-recon`
for baseline execution, Scope partitioning, Provider status, artifacts, resume,
and closure.

## Choose An Extension

Select one extension only when a concrete artifact supports it:

| Signal | Extension |
|---|---|
| Organization, ASN, acquisition, or certificate relationship | Correlate ownership; keep new assets as Scope candidates |
| Resolved host with uncommon service evidence | Expand network inventory within written Scope |
| JavaScript bundle or Source Map | Extract routes, schemas, parameters, and client-visible trust assumptions |
| GraphQL path or schema reference | Expand GraphQL mapping and load the GraphQL specialist |
| OpenAPI, Swagger, mobile API, or versioned route | Compare methods, versions, roles, and object identifiers |
| Public source repository or package reference | Correlate deployment paths and exposed configuration |
| Cloud identifier | Confirm ownership first, then inspect only permitted resources |
| Stable response anomaly | Create a lead with one changed variable and a negative control |

Run a supported branch with `bb-recon expand`. Use a direct Provider only when
the branch is not represented by the executor. Store its command, rate, input,
output, and reason under `recon/branches/`; do not mix it into baseline coverage.

## Guardrails

- Match every active target against written Scope immediately before use.
- Treat shared domains, brands, certificates, CDNs, and repositories as
  relationship evidence, not authorization.
- Keep archive and passive discoveries inert until matched to Scope.
- Set explicit request rates and time limits for active Providers.
- Record missing credentials or Providers as coverage limits.
- Continue unfinished baseline stages after exploring an early signal.
- Promote results to leads only when they expose a concrete trust boundary,
  identity difference, state transition, or reproducible response delta.

Do not use a five-minute rule or target score to declare Recon complete. Those
heuristics may reprioritize a lead, but `recon/coverage.json` owns baseline
completion.
