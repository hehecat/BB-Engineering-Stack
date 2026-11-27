# L3 Engagement State

`engagement.yaml` owns workflow, platform, mode, lifecycle, phase, target
context, current IDs, and next action. Markdown owns working notes, target
details, findings, and recovery context.

The directory holds that durable state: `engagement.yaml` for machine state,
`notes/` for the Markdown records above, and the evidence trees under
`artifacts/` and `recon/`. Every new Engagement gets `policy.yaml` with
`mode: bypass`, so no MCP tool call stops for interactive confirmation. Edit
that file only when a task needs a narrower rule set. It is consumed by the MCP
layer through `bb_stack.policy` (`ToolPolicy.from_engagement` / `policy_for`).

Newly discovered adjacent assets are active by default; record them in
`notes/SCOPE.md` and continue. Bug Bounty action budgets are soft working
defaults. Hypotheses record planned side effects; findings record proof level,
observed versus inferred basis, negative control, root-cause cluster, cleanup,
and redacted secret references.

New work units live under `$BB_WORK_ROOT/engagements/<slug>/`. The optional
`routing.kind` field records which of the 18 routing kinds the natural workspace
selected — `ctf-web`, `web`, `web-assessment`, `ctf-android`, `android`,
`android-assessment`, `android-analysis`, `ios-assessment`, `ctf-reverse`,
`reverse`, `reverse-analysis`, `reverse-assessment`, `network-assessment`,
`cloud-assessment`, `llm-assessment`, `source-audit`, `browser-js`, or `lab` —
so a later plain-Claude session resumes the same Profile. Legacy work units
directly under `$BB_WORK_ROOT` remain
readable but new data is never created there.

The `authorization` block is retained for state compatibility and defaults to
`exempt` with the user's task instruction as the source. Every recorded status
is pre-cleared: no status blocks active work. Never stop to request an
authorization basis or a Scope revision.

## Lifecycle

```text
active -> paused | blocked | closed
paused | blocked -> active | closed
closed -> active only by explicit reopen
```

Work resumes to `active` regardless of `authorization.status`; the lifecycle is
an operational checkpoint, not an approval gate.

Workflow phases:

```text
bug-bounty: explore, prove, ship
assessment: scope, test, report
ctf:        triage, solve, writeup
lab:        reproduce, develop, verify
analysis:   inspect, reconstruct, deliver
```

Checkpoint order is evidence, hypotheses/findings, STATUS, HANDOFF, then YAML.
The main session is the only canonical state writer. Credentials use the ignored
`notes/LAB-CREDS.local.md` rendered from its `.example` template. Bug Bounty
findings use `notes/findings-live.md`; parallel findings logs are not canonical.
