# L3 Engagement State

`engagement.yaml` owns workflow, platform, mode, lifecycle, phase, normalized
scope, current IDs, and next action. Markdown owns written scope, working notes,
findings, and recovery context.

Newly discovered adjacent assets remain `candidate` entries until a written
authorization source promotes them through a Scope revision. Bug Bounty Scope
records the current production action budget. Hypotheses record planned side
effects; findings record proof level, observed versus inferred basis, negative
control, root-cause cluster, cleanup, and redacted secret references.

New work units live under `$BB_WORK_ROOT/engagements/<slug>/`. The optional
`routing.kind` field records whether the natural workspace selected CTF Web,
Web/BB, assessment domain, Browser-JS, Android, Reverse, or Lab so a later
plain-Claude session resumes the same Profile. Legacy work units directly under
`$BB_WORK_ROOT` remain
readable but new data is never created there.

## Lifecycle

```text
active -> paused | blocked | closed
paused | blocked -> active
closed -> active only by explicit reopen
```

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
