# BB Engineering Stack

[简体中文](README.zh-CN.md) | English

Portable, headless-first Claude Code security harness for CTF, Bug Bounty/VDP,
authorized Web/API, Android, iOS, network, cloud, LLM/agent, source and supply
chain assessment, browser JavaScript analysis, and reverse engineering.

## Boundaries

```text
$BB_STACK_ROOT   system source, profiles, Skills, schemas, tests
$BB_WORK_ROOT    user-selected Claude security workspace root
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
| `02-L2-Workflow-Profiles/` | workflow x domain x platform Prompt composition |
| `03-L3-Engagement-State/` | scope, state, templates, lifecycle |
| `04-L4-Skills/` | manifest, orchestrators, specialist Skills |
| `05-L5-MCP-CLI/` | capability registry, MCP render, doctor |
| `90-Docs/` | user and maintainer documentation |
| `99-Verification/` | isolated behavioral and contract tests |

## Quick Start

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces"
source "$HOME/.config/bb-stack/env.sh"
bb-stack configure
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp
bb-stack eval contracts
cd "$BB_WORK_ROOT"
claude
```

No engagement data belongs in this source repository. The suggested work root
is not fixed; select another dedicated directory with `--work-root`. The
workspace router creates or resumes `engagements/<slug>/` from normal Claude
conversation. Explicit `new` and `launch` commands remain available for strict
reproduction and profile-specific MCP isolation.

Browser JavaScript tasks route independently from CTF and Bug Bounty. The
workflow uses the managed Chrome DevTools CLI in normal workspace sessions,
Chrome DevTools MCP in strict launches, and `webcrack` for selected static
reconstruction. Deliverables are selected from the requested outcome rather
than fixed to a user script or browser extension.

Normal use remains plain conversation:

```bash
cd "$BB_WORK_ROOT"
claude
```

The workspace router first selects Bug Bounty, authorized assessment, CTF,
standalone analysis, or Lab, then selects Web/API, Android, iOS, network, cloud,
LLM/agent, source, Browser-JS, or reverse. The same APK therefore routes
differently for a CTF solve, a mobile assessment, and algorithm reconstruction.

```bash
bb-stack bootstrap --profile browser-js
bb-stack workspace route --kind browser-js --target https://app.example
bb-stack doctor --profile browser-js --strict --probe-mcp
```

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

Android and native reverse work no longer assumes CTF. Explicit examples:

```bash
bb-stack bootstrap --profile android
bb-stack launch --profile ctf-android --engagement APK-SLUG
bb-stack bootstrap --profile assessment-android
bb-stack launch --profile assessment-android --engagement MOBILE-SLUG
bb-stack bootstrap --profile analysis-android
bb-stack launch --profile analysis-android --engagement ANALYSIS-SLUG
bb-stack bootstrap --profile reverse
bb-stack launch --profile ctf-reverse --engagement BINARY-SLUG
```

Android static routing uses `android-reverse-engineering` for APK/XAPK/JAR/AAR
fingerprinting, decompilation, Kotlin/R8 name recovery, API extraction, and call
flows. `android-pentest` remains the security specialist for components, ADB,
Frida, storage, TLS, and runtime validation.

Authorized non-BB assessments use `security-orchestrator` and one domain
specialist. Profiles are isolated: cross-domain leads may load an optional
Skill, but workflow, scope, platform policy, and MCP composition do not switch.
The root `.mcp.json` intentionally contains no domain MCP; strict launches load
only the current Profile's MCP, while normal browser work uses the managed
`chrome-devtools` CLI.

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
