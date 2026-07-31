# BB Engineering Stack

Portable, headless-first Claude Code environment for CTF Web, Bug Bounty, VDP,
authorized Web/API testing, Android static analysis, and reverse engineering.

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
bb-stack configure
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp
bb-stack eval contracts
bb-stack new --workflow ctf --platform standalone-ctf challenge-name TARGET
bb-stack launch --profile ctf-quick --engagement challenge-name
```

No engagement data belongs in this source repository.

`bb-stack` is the control plane for the complete lifecycle. `bb-claude` is only
a convenience wrapper around `bb-stack launch`.

```text
bootstrap -> configure -> status -> eval -> new -> launch -> checkpoint -> portable export
```

For Bug Bounty use `bootstrap --profile web`, create a `bug-bounty` Engagement,
then launch `bb-interactive` or `bb-continuous`. The unified status view reports
resolved roots, Prompt composition, Engagement state, Claude/Codex Skills,
MCP/CLI providers, proxy application, personal integrations, and exact repair
actions.

Android and native reverse profiles use the same CTF Engagement lifecycle:

```bash
bb-stack bootstrap --profile android
bb-stack launch --profile ctf-android --engagement APK-SLUG
bb-stack bootstrap --profile reverse
bb-stack launch --profile ctf-reverse --engagement BINARY-SLUG
```

Run a real, isolated Claude behavior check after moving machines or changing
Prompt routing:

```bash
bb-stack eval agent --profile ctf-quick
bb-stack status --profile ctf-web --require-agent-eval --strict
```

See [`90-Docs/QUICKSTART.md`](90-Docs/QUICKSTART.md) for the end-to-end flow and
[`90-Docs/CONFIGURATION.md`](90-Docs/CONFIGURATION.md) for machine-local roots,
proxy, HackerOne identity, OTP, file delivery, and Keysmith.

Check pinned dependencies without changing them:

```bash
bb-stack updates check --all
```

See [`90-Docs/UPDATES.md`](90-Docs/UPDATES.md) for staging, validation,
promotion, rollback, and extension contracts.

Before switching computers, export only portable non-secret intent and back up
Engagements separately:

```bash
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

See [`90-Docs/MIGRATION.md`](90-Docs/MIGRATION.md) for preview-first restore and
the explicit secret restoration checklist.
