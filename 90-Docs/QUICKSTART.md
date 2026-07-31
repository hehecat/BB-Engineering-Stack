# Fresh Machine Quick Start

Supported primary environment: Linux x86_64 or arm64, Python 3.11+, headless or
desktop. Claude Code authentication must already work.

The stack does not export `CLAUDE_CONFIG_DIR` by default, preserving Claude
Code's existing state location. Set it before bootstrap only when the existing
Claude installation already uses a custom config directory.

## CTF Web

```bash
git clone YOUR_STACK_REMOTE "$HOME/BB-Engineering-Stack"
cd "$HOME/BB-Engineering-Stack"
./00-L0-Runtime/bin/bootstrap --profile ctf-web
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile ctf-web --strict --probe-mcp

bb-stack new ctf-demo https://challenge.example \
  --workflow ctf --platform standalone-ctf
bb-stack launch --profile ctf-quick --engagement ctf-demo
```

## Bug Bounty Or VDP

```bash
./00-L0-Runtime/bin/bootstrap --profile web
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile web --strict --probe-mcp

bb-stack new example-bb https://example.com \
  --workflow bug-bounty --platform generic-vdp --mode interactive
bb-stack launch --profile bb-interactive --engagement example-bb
```

For HackerOne, set `BB_H1_USERNAME` in `$BB_CONFIG_HOME/config.env`, create with
`--platform hackerone`, then copy current written program rules into
`notes/SCOPE.md` before testing. For Butian use `--platform butian`; it does not
inherit HackerOne identity or report fields.

For a continuous engagement, create it with `--mode continuous`, inspect it
with `bb-stack status --profile web --engagement example-bb`, and launch
`bb-continuous`. The status command inherits the Engagement platform and mode;
for example, a HackerOne Engagement automatically checks `BB_H1_USERNAME`.

## Proxy

Edit `$BB_CONFIG_HOME/config.env`:

```bash
BB_PROXY_MODE="mihomo"
BB_HTTP_PROXY="http://127.0.0.1:7890"
BB_SOCKS_PROXY="socks5://127.0.0.1:7891"
```

Source `env.sh` again, then verify `proxy mode`, `applied`, and `listener` in
`bb-stack status` output.
Set non-default stack/work/config roots in the environment before running
bootstrap; generated `env.sh` preserves those resolved roots. `config.env` owns
only machine options such as proxy, tester identity, and local service URLs.
Add uncommon global binary directories through colon-separated `BB_EXTRA_PATH`;
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
bb-stack launch --profile bb-interactive --engagement example-bb
bb-stack engagement checkpoint example-bb
bb-stack engagement pause example-bb --reason 'switching machine'
bb-stack engagement resume example-bb
```

From inside an Engagement directory, `bb-stack status --profile web` detects
that work unit automatically. `bb-claude` remains available as a shorter launch
wrapper, but it is not required for the workflow.

## Update Audit

After sourcing `env.sh`, check all pins without changing them:

```bash
bb-stack updates check --all --json > update-audit.json
```

Review `90-Docs/UPDATES.md` before staging or promoting a candidate. The update
manager never runs in the background.
