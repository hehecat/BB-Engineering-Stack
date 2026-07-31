# L3 Engagement State

`engagement.yaml` owns workflow, platform, mode, lifecycle, phase, normalized
scope, current IDs, and next action. Markdown owns written scope, working notes,
findings, and recovery context.

## Lifecycle

```text
active -> paused | blocked | closed
paused | blocked -> active
closed -> active only by explicit reopen
```

Workflow phases:

```text
bug-bounty: explore, prove, ship
ctf:        triage, solve, writeup
lab:        reproduce, develop, verify
```

Checkpoint order is evidence, hypotheses/findings, STATUS, HANDOFF, then YAML.
The main session is the only canonical state writer. Credentials use the ignored
`notes/LAB-CREDS.local.md` rendered from its `.example` template.
