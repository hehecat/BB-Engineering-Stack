# BB Engineering Stack Steward

This repository is the stack source, not a target workspace. Never store target
recon, credentials, extracted applications, evidence, or reports here. Those
belong under the configured `BB_WORK_ROOT/engagements/<slug>/`.

## Own The Setup

The primary interface is conversation. Operate the stack commands yourself;
do not require the user to learn Profiles, route kinds, bootstrap flags, or
repair commands.

When the user asks to install, initialize, check, repair, configure, migrate, or
update the stack:

1. Inspect the repository, existing `~/.config/bb-stack/config.env`, Claude Code
   availability, and any existing workspace before asking for information.
2. If no work root has been selected, recommend `$HOME/BB-Workspaces` and ask
   one compact question only when the user has not accepted the default.
3. Bootstrap `minimal` first. It is the natural-language control plane; domain
   Profiles are installed automatically when a routed task needs them.
4. Preserve existing Claude login state, local permissions, personal config,
   and Engagement data. Never use `--force` over local changes without showing
   the conflict and obtaining a clear decision.
5. Verify workspace status and the installed Profile after changes. Diagnose
   and retry commands yourself. Ask the user only for an external prerequisite
   such as a proxy preference, account identity, mailbox authorization, device,
   credential, or written Scope that cannot be inferred locally.

For a Stack version update, run `bb-stack update --check`, then
`bb-stack update`. If an older installation has no saved Bootstrap Profile,
use `bb-stack update --profile minimal` once and continue installing domain
Profiles on demand. Do not substitute plural `bb-stack updates`; that command
only manages Skill, MCP, and tool candidates.

Treat SecLists, PayloadsAllTheThings, and Trickest wordlists as managed data,
not generic tool directories. Use `bb-stack data status` and the reported
`bb-stack data ensure` action; directory existence alone is not readiness.
Never move catalog pins in the background. Review the upstream change and
sentinels first.

Personal integrations are optional. Do not block first use on HackerOne,
FileCodeBox, mailbox OTP, mobile devices, cloud credentials, or Keysmith.
Configure them when the user asks or when the active task actually requires
them. Never print stored secrets.

## Route Security Work

If the user supplies a security task while Claude is open in this source
repository:

1. Ensure the minimal runtime and workspace exist. If they do not, perform the
   setup above.
2. Source `$BB_CONFIG_HOME/env.sh`, resolve `BB_WORK_ROOT`, and read its generated
   `CLAUDE.md`.
3. Follow that workspace router, run its route command, read every returned
   Prompt and state file, run returned repair commands, and continue the task
   inside the returned Engagement directory.

Do not ask the user to restart Claude merely because the initial conversation
started in this repository. Do not perform target work in the source tree.

## Maintain The Source

For repository changes, preserve the L0-L5 ownership boundaries and prefer
registries, schemas, generated templates, and tests over machine-specific
edits. Keep usernames, absolute home paths, tokens, credentials, target data,
and generated runtime state out of Git. Run the focused tests for changed
behavior and `99-Verification/scripts/run-all.sh` before release-level commits.
For managed component updates, stage and validate first, show the candidate
diff, and do not run `updates approve` or `updates promote` until an explicit
reviewer identity and review note apply to that exact candidate.

Match the user's language. Keep commands, paths, protocol fields, and raw errors
unchanged.
