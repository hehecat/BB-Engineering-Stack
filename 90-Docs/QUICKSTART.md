# Explicit Operator Quick Start

This is the CLI reference for deterministic setup and automation. Normal users
may start Claude in the cloned source repository and ask it to initialize with
recommended defaults; after that, normal work starts as conversation from the
selected workspace. See the top-level README for that path.

Supported primary environment: Linux x86_64 or arm64, Python 3.11+, headless or
desktop. Claude Code authentication must already work.

The stack does not export `CLAUDE_CONFIG_DIR` by default, preserving Claude
Code's existing state location. Set it before bootstrap only when the existing
Claude installation already uses a custom config directory.

## CTF Web Explicit Setup

```bash
git clone YOUR_STACK_REMOTE "$HOME/BB-Engineering-Stack"
cd "$HOME/BB-Engineering-Stack"
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces"
source "$HOME/.config/bb-stack/env.sh"
bb-stack configure
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp
bb-stack eval contracts

cd "$BB_WORK_ROOT"
claude
# Then say: 这是一个 CTF Web 题目：https://challenge.example
```

`$HOME/BB-Workspaces` is a recommendation, not a fixed location. Select any
dedicated directory with `--work-root`; bootstrap persists the resolved value
in `$BB_CONFIG_HOME/env.sh` and generates the project router there.
The generated project `.mcp.json` contains no domain MCP; strict launches load
only the selected Profile's MCP.

After a new-machine restore or Prompt change, run the bounded real-Agent gate:

```bash
bb-stack eval agent --profile ctf-quick
bb-stack status --profile ctf-web --require-agent-eval --strict
```

The evaluation uses Sonnet with low effort and a 1 USD ceiling by default. It
does not contact a target and keeps the synthetic workspace under
`$BB_CONFIG_HOME/evaluations/`.

## Android And Reverse CTF

Static APK analysis is headless and does not require a connected device:

```bash
./00-L0-Runtime/bin/bootstrap --profile android \
  --work-root "$HOME/BB-Workspaces"
bb-stack status --profile android --strict
bb-stack new apk-challenge ./challenge.apk --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-android --engagement apk-challenge
```

For a native binary or unknown reverse artifact:

```bash
./00-L0-Runtime/bin/bootstrap --profile reverse
bb-stack status --profile reverse --strict
bb-stack new reverse-challenge ./challenge.bin --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-reverse --engagement reverse-challenge
```

The Reverse profile installs the native inventory baseline (`file` and
Binutils) plus pinned Radare2. GDB, QEMU user emulation, hardening checks, and
Ghidra headless analysis remain optional. Start every native artifact with the
`native-reverse-engineering` triage workflow; it preserves the input and writes
its evidence under the active Engagement.

The Android profile installs Java, ADB, Apktool, pinned JADX, the
`android-reverse-engineering` static workflow, and `android-pentest` for security
validation. ADB device and Frida/Objection capabilities remain optional until
dynamic analysis is needed.
The Reverse profile installs pinned Radare2; JADX and Apktool remain optional
mixed-artifact providers.

## Authorized Security Assessment

Use normal conversation; the router distinguishes workflow and domain:

```text
对 product.apk 做 Android 安全审计
反编译 library.apk 并还原算法，不做漏洞测试
对 service.elf 做 native 组件安全评估
对 10.20.0.0/24 做内网和 AD 安全评估
审计授权 AWS 账户的 IAM 和存储配置
测试 RAG Agent 的 Prompt Injection、MCP 和 Memory 边界
审计 repository 的源码、IaC、容器和依赖安全
```

Explicit profile setup is available when needed:

```bash
bb-stack bootstrap --profile assessment-android
bb-stack bootstrap --profile assessment-ios
bb-stack bootstrap --profile assessment-reverse
bb-stack bootstrap --profile assessment-network
bb-stack bootstrap --profile assessment-cloud
bb-stack bootstrap --profile assessment-llm
bb-stack bootstrap --profile assessment-source
```

For an explicitly scoped native artifact, record the authorization basis and
route it into the assessment workflow before any dynamic action. The default is
`user-asserted`: record the user's own statement (own asset, provided artifact,
or named program) in `notes/SCOPE.md`, no external letter needed. `verified`
applies when a written authorization document is on file:

```bash
bb-stack workspace route --kind reverse-assessment --target ./service.elf \
  --authorization-status user-asserted --authorization-source "user statement: own artifact"
bb-stack launch --profile assessment-reverse --engagement service-native
```

Provider credentials, iOS devices, Frida, cloud CLIs, and specialized scanners
remain optional machine capabilities and are reported by Doctor.

## Bug Bounty Or VDP

```bash
./00-L0-Runtime/bin/bootstrap --profile web \
  --work-root "$HOME/BB-Workspaces"
source "$HOME/.config/bb-stack/env.sh"
bb-stack configure
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile web --strict --probe-mcp

bb-stack new example-bb https://example.com \
  --workflow bug-bounty --platform generic-vdp --mode interactive
bb-recon run example-bb --json
bb-stack launch --profile bb-interactive --engagement example-bb
```

For HackerOne, run `bb-stack configure --h1-username NAME`, create with
`--platform hackerone`, then copy current written program rules into
`notes/SCOPE.md` before testing. For Butian use `--platform butian`; it does not
inherit HackerOne identity or report fields.

For a continuous engagement, create it with `--mode continuous`, inspect it
with `bb-stack status --profile web --engagement example-bb`, and launch
`bb-continuous`. The status command inherits the Engagement platform and mode;
for example, a HackerOne Engagement automatically checks `BB_H1_USERNAME`.

## Proxy

Configure the local proxy:

```bash
bb-stack configure --proxy-mode mihomo \
  --http-proxy http://127.0.0.1:7890 \
  --socks-proxy socks5://127.0.0.1:7891
source "$BB_CONFIG_HOME/env.sh"
```

Source `env.sh` again, then verify `proxy mode`, `applied`, and `listener` in
`bb-stack status` output.
Set non-default stack/work/config roots in the environment before running
bootstrap; generated `env.sh` preserves those resolved roots. `config.env` owns
only machine options such as proxy, tester identity, and local service URLs.
Add uncommon global binary directories with `bb-stack configure --extra-path`;
the runtime does not inherit arbitrary project paths from the parent shell.

Use the status dashboard after every machine-local change:

```bash
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile web --platform hackerone
bb-stack status --profile web --platform hackerone --check-external
```

The second command may contact configured mailbox and file-delivery services;
the first remains local except for optional MCP handshakes when `--probe-mcp`
is supplied. See `90-Docs/CONFIGURATION.md` for every personal setting.

Optional OTP mailbox setup is available without a separate package:

```bash
bb-stack mail configure --provider gmail --user operator@gmail.com
bb-stack mail test
```

## Session Lifecycle

```bash
bb-stack engagement validate example-bb
bb-stack engagement authorize example-bb --status user-asserted \
  --source 'User statement: own application under test'
bb-stack launch --profile bb-interactive --engagement example-bb
bb-stack engagement checkpoint example-bb
bb-stack engagement pause example-bb --reason 'switching machine'
bb-stack engagement resume example-bb
```

The normal entry is `cd "$BB_WORK_ROOT" && claude`. The workspace `CLAUDE.md`
routes natural-language tasks and continuations. From inside an Engagement,
`bb-stack status --profile web` detects that work unit automatically.
`bb-claude` remains available for explicit Prompt and MCP isolation.

Validate the natural-language matrix after a Prompt or model change:

```bash
./99-Verification/scripts/router-agent-smoke.sh
```

## Update An Existing Installation

Check the configured Git remote without changing the working tree:

```bash
bb-stack update --check
```

Fast-forward the current branch, preflight the updated Bootstrap, then refresh
the runtime, installed Skills, data assets, and Workspace-managed files:

```bash
bb-stack update
```

Bootstrap saves the last successful Capability Profile in
`$BB_CONFIG_HOME/install.json`. An installation created by an older release has
no marker; provide the correct Profile once:

```bash
bb-stack update --profile minimal
```

Use `--dry-run` for a read-only remote comparison and planned refresh. Use
`--skip-tools`, `--skip-node`, `--skip-skills`, or `--with-optional` with the
same meanings as Bootstrap. Non-refreshing `--check` and `--dry-run` tolerate local
source edits. A real update stops before fetching when tracked source files are dirty,
fast-forwards only to the revision it fetched, rejects non-fast-forward
histories, refuses to merge a differently named remote branch into the checked
out branch, and never forces Workspace files.
If Bootstrap fails after the fast-forward, the command reports that boundary;
fix the local installation issue and rerun `bb-stack update` to retry.

## Component Update Audit

After sourcing `env.sh`, check all pins without changing them:

```bash
bb-stack updates check --all --json > update-audit.json
```

Review `90-Docs/UPDATES.md` before staging or promoting a candidate. The update
manager never runs in the background. `bb-stack updates` manages component
candidates; it does not update the Stack source repository.
