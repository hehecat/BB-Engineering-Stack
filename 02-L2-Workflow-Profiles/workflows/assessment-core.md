# Authorized Security Assessment Workflow

The user-supplied authorization and `notes/SCOPE.md` own targets, identities,
rates, side effects, credentials, and exclusions. Read `engagement.yaml`,
`notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md` before testing.

Before active target traffic, require `lifecycle: active` and
`authorization.status: verified` in `engagement.yaml`, with the written source
recorded in `notes/SCOPE.md`. If authorization is pending, user-asserted, or
revoked, stop active testing, preserve state, and complete the authorization
repair first. Never infer verification from credentials or network access.

Start or resume through `security-orchestrator`, then load only the domain Skill
needed by the active lead. Keep scope and lifecycle policy in this workflow;
do not inherit Bug Bounty submission rules, CTF flag goals, or standalone
analysis acceptance criteria from another Profile.

Capture baselines, changed inputs, identity or privilege context, observed
deltas, evidence paths, cleanup, and exact next action in
`notes/findings-live.md`. Save large raw output under `artifacts/` and reusable
commands or code under `scripts/`. Use `reports/` and `deliverables/` only when
the user requests a review or handoff.

Cross-domain work is allowed when it remains inside the written Scope. Treat it
as a specialist handoff inside this Engagement; do not switch workflow or
platform policy merely because a Web, cloud, mobile, source, or network lead
appears.
