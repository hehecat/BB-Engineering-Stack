# BB Engineering Stack

Portable, headless-first Claude Code environment for CTF Web, Bug Bounty, VDP,
and authorized Web/API testing.

## Boundaries

```text
$BB_STACK_ROOT   system source, profiles, Skills, schemas, tests
$BB_WORK_ROOT    real engagements, evidence, reports, local credentials
$BB_CONFIG_HOME  machine-local configuration, no secrets in source
```

Defaults:

```text
BB_STACK_ROOT=$HOME/BB-Engineering-Stack
BB_WORK_ROOT=$HOME/BB-Workspaces
BB_CONFIG_HOME=$HOME/.config/bb-stack
```

## Layers

| Directory | Owner |
| --- | --- |
| `00-L0-Runtime/` | bootstrap, runtime, proxy, PATH, launchers |
| `01-L1-Global-Prompt/` | platform-neutral personal behavior |
| `02-L2-Workflow-Profiles/` | CTF/BB workflows and platform profiles |
| `03-L3-Engagement-State/` | scope, state, templates, lifecycle |
| `04-L4-Skills/` | manifest, orchestrators, specialist Skills |
| `05-L5-MCP-CLI/` | capability registry, MCP render, doctor |
| `90-Docs/` | user and maintainer documentation |
| `99-Verification/` | isolated behavioral and contract tests |

## Quick Start

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web
source "$HOME/.config/bb-stack/env.sh"
bb-stack doctor --profile ctf-web --strict --probe-mcp
bb-stack new --workflow ctf --platform standalone-ctf challenge-name TARGET
bb-claude --profile ctf-quick --engagement "$HOME/BB-Workspaces/challenge-name"
```

No engagement data belongs in this source repository.

For Bug Bounty use `bootstrap --profile web`, create a `bug-bounty` engagement,
then launch `bb-interactive` or `bb-continuous`. See
[`90-Docs/QUICKSTART.md`](90-Docs/QUICKSTART.md).

Check pinned dependencies without changing them:

```bash
bb-stack updates check --all
```

See [`90-Docs/UPDATES.md`](90-Docs/UPDATES.md) for staging, validation,
promotion, rollback, and extension contracts.
