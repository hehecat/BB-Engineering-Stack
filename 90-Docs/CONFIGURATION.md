# Machine Configuration

## Unified Entry

Use `bb-stack` for setup, inspection, Engagement lifecycle, launch, and updates:

```bash
bb-stack status --profile ctf-web
bb-stack status --profile web --platform hackerone
bb-stack status --profile web --engagement PROGRAM-SLUG --strict
```

Use the interactive configurator for first setup:

```bash
bb-stack configure
source "$BB_CONFIG_HOME/env.sh"
```

For scripts and headless provisioning, pass only the settings being changed:

```bash
bb-stack configure --proxy-mode mihomo \
  --http-proxy http://127.0.0.1:7890 \
  --socks-proxy socks5://127.0.0.1:7891
bb-stack configure --h1-username your-hackerone-username
bb-stack configure --agent-language zh-CN
bb-stack configure --npm-registry auto
bb-stack configure --show
```

The dashboard reports L0-L5 state and prints ordered repair actions. Human and
JSON output omit configured passwords, URL credentials, paths after a service
origin, query strings, mailbox contents, and tokens. External service checks
run only with `--check-external`; MCP processes are started only with
`--probe-mcp`.

## Resolved Roots

Select the work root directly during bootstrap. The shown path is recommended,
not fixed:

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces"
```

For fully custom source and configuration roots, set them in the shell before
bootstrap:

```bash
export BB_STACK_ROOT="$HOME/src/BB-Engineering-Stack"
export BB_CONFIG_HOME="$HOME/.config/bb-stack"
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/security-work"
```

Generated `$BB_CONFIG_HOME/env.sh` preserves these roots. Do not place them in
`config.env`; bootstrap removes managed root assignments from that file. Check
the active values with `bb-stack status` or `bb-stack paths`.

`BB_DATA_ROOT` is derived from `$BB_STACK_ROOT/.runtime/data` and is exported
to Claude workspace settings and strict launches. Do not set it in
`config.env`; use `bb-stack data path DATASET` to resolve a managed repository.

To select a different work root later without reinstalling tools:

```bash
bb-stack workspace init --work-root "$HOME/New-Security-Work"
source "$BB_CONFIG_HOME/env.sh"
```

The selected root contains `CLAUDE.md`, `.mcp.json`, project-local Claude
environment settings, `inbox/`, and `engagements/`. bb-stack owns
`.claude/settings.json`; Claude Code and the user own
`.claude/settings.local.json` for MCP approvals and local permissions. Existing
bb-stack-managed files with local edits are not overwritten unless `--force`
is supplied.

## Machine Options

`bb-stack configure` owns `$BB_CONFIG_HOME/config.env` and regenerates
`env.sh`. The config is parsed as literal assignments; generated shell code
does not source the editable file. Existing unknown extension assignments are
preserved but are not loaded or included in portable exports.

| Variable | Purpose | Default |
| --- | --- | --- |
| `BB_PROXY_MODE` | `direct` or `mihomo` | `direct` |
| `BB_HTTP_PROXY` | mihomo HTTP endpoint | `http://127.0.0.1:7890` |
| `BB_SOCKS_PROXY` | mihomo SOCKS endpoint | `socks5://127.0.0.1:7891` |
| `BB_H1_USERNAME` | HackerOne tester identity | empty |
| `BB_FILECODEBOX_URL` | FileCodeBox base origin | empty |
| `BB_AGENT_LANGUAGE` | Agent visible output language: `zh-CN` or `en` | `zh-CN` |
| `BB_NPM_REGISTRY` | `auto`, `npmjs`, `npmmirror`, or a custom HTTPS origin | `auto` |
| `BB_EXTRA_PATH` | uncommon global binary paths, colon-separated | empty |

## Recon Search Sources

Recon can optionally query Exa, Tavily, and Brave Search during the
`organization-assets` stage. Results are stored as JSONL artifacts and are
treated as scope candidates until explicitly reviewed; a search provider never
expands written scope automatically.

Provide keys through the process environment. They are intentionally not part
of `config.env`, `env.sh`, portable exports, or recon state:

```bash
export EXA_API_KEY=TOKEN
export TAVILY_API_KEY=TOKEN
export BRAVE_SEARCH_API_KEY=TOKEN
```

The providers are independent and optional. Missing keys produce a
`configure-provider` recommendation without blocking required Recon stages.
After configuring a key, rerun the affected stage:

```bash
bb-stack recon rerun ENGAGEMENT --stage organization-assets --cascade
```

After each configuration command, reload the generated environment and run
status:

```bash
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile ctf-web --strict
```

The config parser accepts shell-style literal assignments but does not execute
command substitutions or source the file during status collection.

`BB_NPM_REGISTRY=auto` measures a real package-metadata request against npmjs
and npmmirror, tries the faster reachable registry first, and falls back to the
other registry when installation fails. An explicit value disables fallback.
Runtime selection is passed directly to `npm ci`; it does not rewrite the
source lockfile. Repository and staged update lockfiles always store canonical
`registry.npmjs.org` URLs, independent of global `.npmrc` and
`npm_config_registry` values.

## Proxy Comparison

`direct` clears uppercase and lowercase HTTP proxy variables. `mihomo` requires
the configured HTTP listener to accept TCP connections and the active
`HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` values to match `config.env`.
Conflicting lowercase variables are also detected.

```bash
bb-stack configure --proxy-mode mihomo \
  --http-proxy http://127.0.0.1:7890 \
  --socks-proxy socks5://127.0.0.1:7891
```

After configuring, source `env.sh` again. A listening mihomo service does not enable
proxying by itself; the dashboard distinguishes `listener` from `applied`.

## Platform Identity

Set only the username, not passwords or API tokens:

```bash
bb-stack configure --h1-username your-hackerone-username
```

It is required when the selected platform is `hackerone` and informational for
other platforms. Butian, generic VDP, standalone CTF, and local lab overlays do
not inherit HackerOne request-identification rules.

## OTP Mail Adapter

OTP retrieval is an optional first-party L5 provider installed by bootstrap.
Configure Gmail with an App Password in a hidden terminal prompt:

```bash
bb-stack mail configure --provider gmail --user operator@gmail.com
bb-stack mail test
bb-stack mail wait --timeout 120 --since 10
bb-stack mail list --limit 5 --since 1440
```

The standalone compatibility commands remain available:

```text
mail-otp --test
mail-otp --wait 120 --since 10
mail-otp --list 5
mail-otp-set-pass
```

`latest` and `wait` print only the extracted code unless `--json` is explicit.
`list` prints sender, subject, timestamp, UID, and extracted code, never the
message body. Use `--from`, `--subject`, or `--unseen` to narrow a mailbox.

Generic IMAP and Outlook host presets are also supported:

```bash
bb-stack mail configure --provider generic --host imap.example.com \
  --user operator@example.com
bb-stack mail configure --provider outlook --user operator@outlook.com \
  --auth oauth2 --token-stdin
```

Many Microsoft personal and organizational tenants disable password-based IMAP;
use an access token with the `IMAP.AccessAsUser.All` permission in that case.
The built-in XOAUTH2 mode consumes a supplied access token but does not own its
refresh lifecycle.

All provider settings and secrets live only at:

```text
$HOME/.local/share/pentest-mail/config.env
```

The file is atomically written with mode `600`; its parser treats values as
literals and never executes shell substitutions. `mail-otp-set-pass` reads from
a hidden prompt by default. For headless secret injection, use
`--password-stdin` or `--token-stdin` and avoid placing secrets in command-line
arguments.

`bb-stack status --profile web` checks command presence, file mode, required
fields, and the selected authentication secret locally without displaying
their values. With `--check-external`, status runs only `mail-otp --test` and
suppresses its output.

## File Delivery

Set a base HTTP or HTTPS origin without a take code, token, query, or path:

```bash
bb-stack configure --filecodebox-url https://filebox.example
```

Local status validates the URL shape and `curl` provider. With
`--check-external`, it requests the configured `/health` endpoint through the
selected proxy mode. The displayed endpoint is reduced to scheme, host, and
port.

Upload a local artifact through the configured FileCodeBox API with the
first-party command:

```bash
bb-stack filecodebox upload ./artifact.zip --expire-value 7 --expire-style day
```

The command calls `POST /share/file/` as `multipart/form-data` and returns the
share code and retrieval URL as JSON. If guest uploads are disabled, pass the
administrator Bearer token through stdin so it never appears in shell history
or curl process arguments:

```bash
printf '%s\n' "$FILECODEBOX_TOKEN" \
  | bb-stack filecodebox upload ./artifact.zip --token-stdin --json
```

The equivalent API flow for an agent or custom integration is documented in
the [FileCodeBox API reference](https://fcb-docs.aiuo.net/api/):

```text
POST {BB_FILECODEBOX_URL}/share/file/
Content-Type: multipart/form-data
file=@<local-file>
expire_value=<integer>
expire_style=day|hour|minute|count|forever
Authorization: Bearer <token>  # only when guest upload is disabled
```

The successful response contains `detail.code`, which is the retrieval code.
For large files or S3-backed deployments, use the upstream pre-signed flow:
`POST /presign/upload/init`, upload to the returned URL, and call
`POST /presign/upload/confirm/{upload_id}` when `mode` is `direct`.

## Keysmith

Keysmith is optional persistent Prompt deployment for raw `claude` commands.
Per-Engagement `bb-stack launch` does not depend on it.

```bash
bb-stack keysmith status
bb-stack keysmith install --profile ctf-replacement --yes
bb-stack status --profile ctf-web
```

The status dashboard reports source cache, deployment state, deployed profile,
and managed Prompt drift. It recommends a replacement only when one matches the
selected capability profile; it does not recommend a CTF replacement for a Web
Bug Bounty profile.

## Updates

Update the Stack source and refresh the local installation explicitly:

```bash
bb-stack update --check
bb-stack update
```

The successful Bootstrap Profile is stored in `$BB_CONFIG_HOME/install.json`
with mode `600`. Existing installations without this marker must pass
`--profile PROFILE` once. Non-refreshing `--check` and `--dry-run` tolerate local
source edits; `--check` may refresh Git's remote metadata, while a real update requires a clean Git worktree, fetches the
selected remote branch, accepts only a fast-forward, runs the updated Bootstrap
in a child process, and preserves the configured `BB_WORK_ROOT`. A Bootstrap
dry run executes before persistent refresh so locally changed Workspace-managed
files stop the operation before they are overwritten. Source fast-forward and
local refresh are separate transactions: if Bootstrap fails, the source remains
at the fetched revision and rerunning `bb-stack update` retries the local refresh.

Status checks installed state; component update discovery remains a separate
read-only operation so it never slows normal launch or changes the machine
implicitly:

```bash
bb-stack updates check --all
```

The singular `update` command owns Stack source refresh. The plural `updates`
command owns Skill, MCP, and tool candidates. Stage, validate, promote, and roll
back component candidates through the contracts in `UPDATES.md`.

## Portable Machine Intent

Export a JSON document containing only portable, non-secret settings, relative
root intent, detected Skill profiles, and Engagement inventory metadata:

```bash
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

`BB_EXTRA_PATH`, old-machine absolute roots, mailbox credentials, Claude auth,
cookies, tokens, Engagement evidence, runtime data, and generated Keysmith/MCP
state are excluded. Import is a preview unless `--yes` is supplied. Existing
non-empty destination values win unless `--force` is also supplied:

```bash
bb-stack portable import "$HOME/bb-stack-portable.json"
bb-stack portable import "$HOME/bb-stack-portable.json" --yes
bb-stack portable import "$HOME/bb-stack-portable.json" --yes --force
source "$BB_CONFIG_HOME/env.sh"
```

Import never changes the active roots. Set destination `BB_STACK_ROOT`,
`BB_WORK_ROOT`, and `BB_CONFIG_HOME` before bootstrap.
