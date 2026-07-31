# Engagement Operations

## Create And Resume

```bash
bb-stack new SLUG TARGET --workflow ctf --platform standalone-ctf
bb-stack engagement validate SLUG
bb-claude --profile ctf-quick --engagement SLUG
```

The launcher changes its working directory to the Engagement. Claude reads
`engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md` before
selecting work.

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
