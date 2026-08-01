# Source, Supply Chain, IaC, And Container Domain

Route through `security-orchestrator`, then use `sast-orchestration` for source
review. Add `iac-security`, `container-security`, `sca-security`, or
`threat-modeling` only when the repository contains that surface or the user
requests it.

Inventory languages, frameworks, build manifests, generated code, deployment
descriptors, trust boundaries, and test entry points before scanning. Save raw
scanner output under `artifacts/source/`, reproducible queries under `scripts/`,
and report only findings supported by a reachable call path, effective
configuration, vulnerable dependency use, or demonstrated trust-boundary
impact.
