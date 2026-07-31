# Migration And Backup

The source repository, work data, and machine config are independent:

```text
$BB_STACK_ROOT   commit and clone
$BB_WORK_ROOT    encrypted backup separately
$BB_CONFIG_HOME  recreate or private backup; may contain identity settings
```

Treat the previous mixed workspace as a read-only migration source. Preview first:

```bash
bb-stack engagement migrate "$LEGACY_BB_ROOT/path/to/old-target" NEW-SLUG TARGET \
  --workflow bug-bounty --platform generic-vdp
```

Add `--yes` to copy into `$BB_WORK_ROOT/NEW-SLUG/legacy-import`. The command
excludes Git internals, dependency trees, cookies, and common token files. It
never moves or deletes the source.

After cloning on another computer, bootstrap, restore only `$BB_WORK_ROOT`, run
`bb-stack engagement validate` for each Engagement, then resume from HANDOFF.
