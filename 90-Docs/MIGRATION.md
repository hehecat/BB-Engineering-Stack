# Migration And Backup

The source repository, work data, and machine config are independent:

```text
$BB_STACK_ROOT   commit and clone
$BB_WORK_ROOT    encrypted backup separately
$BB_CONFIG_HOME  recreate through portable import; never copy secrets blindly
```

## Before Leaving The Source Machine

Checkpoint active work, export non-secret machine intent, and back up the work
root separately with encryption:

```bash
bb-stack engagement checkpoint ENGAGEMENT-SLUG
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

The portable JSON includes relative root intent, machine options, detected
Skill profiles, and Engagement inventory. It excludes mailbox secrets,
`BB_EXTRA_PATH`, absolute old-machine roots, Claude auth, cookies, tokens,
private keys, Engagement evidence, dependencies, and generated Prompt/MCP
state. Keep `$BB_WORK_ROOT` as a separate encrypted backup because the JSON is
an inventory, not a copy of work data.

## Restore On The Destination Machine

Choose destination roots before bootstrap, clone the source repository, then
preview and apply the import:

```bash
export BB_STACK_ROOT="$HOME/BB-Engineering-Stack"
export BB_WORK_ROOT="$HOME/BB-Workspaces"
export BB_CONFIG_HOME="$HOME/.config/bb-stack"

./00-L0-Runtime/bin/bootstrap --profile ctf-web
source "$BB_CONFIG_HOME/env.sh"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
bb-stack portable import "$HOME/bb-stack-portable.json"
bb-stack portable import "$HOME/bb-stack-portable.json" --yes
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp
```

Import preserves every existing non-empty destination setting. Use
`--yes --force` only after reviewing the preview when the exported values
should replace destination values. Root paths are never changed by import.

Restore `$BB_WORK_ROOT` from its encrypted backup, authenticate Claude Code,
and configure local secrets again:

```bash
bb-stack mail configure
bb-stack engagement list
bb-stack engagement validate ENGAGEMENT-SLUG
```

Use the `restore_checklist` in the portable document to identify source-side
integrations that need local secret setup.

## Legacy Workspace Import

Treat the previous mixed workspace as a read-only migration source. Preview first:

```bash
bb-stack engagement migrate "$LEGACY_BB_ROOT/path/to/old-target" NEW-SLUG TARGET \
  --workflow bug-bounty --platform generic-vdp
```

Add `--yes` to copy into `$BB_WORK_ROOT/NEW-SLUG/legacy-import`. The command
excludes Git internals, dependency trees, cookies, and common token files. It
never moves or deletes the source.

The legacy command copies into a new Engagement and never moves or deletes the
source. After import, validate the Engagement and resume from HANDOFF.
