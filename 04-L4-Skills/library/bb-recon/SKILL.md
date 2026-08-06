---
name: bb-recon
description: Use when starting, resuming, reviewing, expanding, or closing Bug Bounty reconnaissance for an Engagement.
owner: hehecat
---

# Bug Bounty Recon

Use `bb-recon` as the coverage executor. Keep the Agent responsible for scope
judgment, signal interpretation, adaptive branches, and lead selection.

## Execute

1. Read `engagement.yaml` and `notes/SCOPE.md`.
2. Run `bb-recon status [ENGAGEMENT] --json` before choosing an action.
3. Run `bb-recon run [ENGAGEMENT] --json` when no baseline exists.
4. Run `bb-recon resume [ENGAGEMENT] --json` when any baseline stage is
   `pending`, `blocked`, or `running`.
5. Read `recon/coverage.json`, then inspect the referenced artifacts.

Do not reimplement the baseline by manually chaining Provider commands. Use
`bb-recon --help` for the command interface. Use direct Providers only for an
adaptive branch that the executor does not express.

## Preserve Coverage

- Treat `completed` as covered, `partial` as covered with visible limits, and
  `blocked` as unfinished.
- Do not report Recon complete while any baseline stage is unfinished.
- Do not hide missing optional Providers, data bundles, failed commands, open
  signals, or unresolved Scope candidates.
- Keep discovered candidate assets inert. Revise written Scope before active
  requests to them.
- Resume unfinished work only. Do not rerun completed stages to create activity.

## Expand Signals

Immediately investigate a high-signal branch when it can change prioritization,
even while the baseline continues. Run:

```bash
bb-recon expand [ENGAGEMENT] --area AREA --target TARGET \
  --reason REASON --signal SIGNAL_ID --json
```

An adaptive branch supplements the baseline; it never replaces unfinished
baseline stages. Record the concrete signal and why the branch outranks other
leads. Use specialist Skills on branch artifacts when useful.

## Close

Close only after all baseline stages are terminal and every visible decision is
resolved. Expand open signals or explicitly accept them. Revise Scope for valid
candidates or explicitly defer them. Acknowledge optional coverage gaps with
their IDs. Supply every accepted ID to `bb-recon close`; never edit state JSON
to force completion.
