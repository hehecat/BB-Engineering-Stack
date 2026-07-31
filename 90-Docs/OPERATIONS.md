# Engagement Operations

## Create And Resume

```bash
bb-stack new SLUG TARGET --workflow ctf --platform standalone-ctf
bb-stack status --profile ctf-web --engagement SLUG --strict
bb-stack engagement validate SLUG
bb-stack launch --profile ctf-quick --engagement SLUG
```

The launcher changes its working directory to the Engagement. Claude reads
`engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md` before
selecting work.

For Bug Bounty, use profile `web` with `bb-interactive` or `bb-continuous`.
`bb-stack status --profile web --engagement SLUG` derives the platform and mode
from `engagement.yaml`, then checks the matching personal requirements.

## Lifecycle

```bash
bb-stack engagement checkpoint SLUG
bb-stack engagement pause SLUG --reason 'external dependency'
bb-stack engagement resume SLUG
bb-stack engagement close SLUG --reason 'completed'
bb-stack engagement reopen SLUG
```

Before pausing or switching computers, update evidence references, exact next
action, STATUS, HANDOFF, then checkpoint YAML. Keep credentials only in ignored
local files with mode 600.

## Continuous Mode

Use an Engagement created with `--mode continuous` and launch
`bb-continuous`. Specialist Skill pivot rules close one lead; they do not close
the Engagement. SHIP starts only when requested.

## Unified Status

Run the local dashboard before launch, after configuration changes, and after
moving the stack to another machine:

```bash
bb-stack status --profile ctf-web
bb-stack status --profile web --platform hackerone --probe-mcp
bb-stack status --profile web --engagement SLUG --strict --json
```

`--strict` returns nonzero only for required failures. Missing optional OTP,
file delivery, Codex Skills, or Keysmith deployment remains visible without
blocking an unrelated CTF workflow. `--check-external` is opt-in because it
contacts configured external services.

## Agent Evaluation

```bash
bb-stack eval contracts
bb-stack eval agent --profile ctf-quick
bb-stack status --profile ctf-web --require-agent-eval --strict
```

The contract suite makes no model call. The Agent suite creates a synthetic
Engagement under `$BB_CONFIG_HOME/evaluations`, allows only local read/write,
and stores a scored report without target data. Status marks a report stale
when the stack version, rendered Prompt digest, routed Skill content, or
evaluation contract changes. Without
`--require-agent-eval`, missing or stale evaluation is visible but optional.

## Machine Configuration And Handoff

```bash
bb-stack configure
source "$BB_CONFIG_HOME/env.sh"
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

On a destination machine, bootstrap first, preview with `portable import`, then
apply with `--yes`. Restore Engagement content from its separate encrypted
backup and use the emitted secret checklist for local-only integrations.
