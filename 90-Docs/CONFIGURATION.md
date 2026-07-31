# Machine Configuration

## Unified Entry

Use `bb-stack` for setup, inspection, Engagement lifecycle, launch, and updates:

```bash
bb-stack status --profile ctf-web
bb-stack status --profile web --platform hackerone
bb-stack status --profile web --engagement PROGRAM-SLUG --strict
```

The dashboard reports L0-L5 state and prints ordered repair actions. Human and
JSON output omit configured passwords, URL credentials, paths after a service
origin, query strings, mailbox contents, and tokens. External service checks
run only with `--check-external`; MCP processes are started only with
`--probe-mcp`.

## Resolved Roots

Set non-default roots in the shell before the first bootstrap:

```bash
export BB_STACK_ROOT="$HOME/src/BB-Engineering-Stack"
export BB_WORK_ROOT="$HOME/security-work"
export BB_CONFIG_HOME="$HOME/.config/bb-stack"
./00-L0-Runtime/bin/bootstrap --profile ctf-web
```

Generated `$BB_CONFIG_HOME/env.sh` preserves these roots. Do not place them in
`config.env`; bootstrap removes managed root assignments from that file. Check
the active values with `bb-stack status` or `bb-stack paths`.

## Machine Options

Edit `$BB_CONFIG_HOME/config.env`, keep it mode `600`, then reload `env.sh`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `BB_PROXY_MODE` | `direct` or `mihomo` | `direct` |
| `BB_HTTP_PROXY` | mihomo HTTP endpoint | `http://127.0.0.1:7890` |
| `BB_SOCKS_PROXY` | mihomo SOCKS endpoint | `socks5://127.0.0.1:7891` |
| `BB_H1_USERNAME` | HackerOne tester identity | empty |
| `BB_FILECODEBOX_URL` | FileCodeBox base origin | empty |
| `BB_EXTRA_PATH` | uncommon global binary paths, colon-separated | empty |

```bash
chmod 600 "$BB_CONFIG_HOME/config.env"
source "$BB_CONFIG_HOME/env.sh"
bb-stack status --profile ctf-web --strict
```

The config parser accepts shell-style literal assignments but does not execute
command substitutions or source the file during status collection.

## Proxy Comparison

`direct` clears uppercase and lowercase HTTP proxy variables. `mihomo` requires
the configured HTTP listener to accept TCP connections and the active
`HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` values to match `config.env`.
Conflicting lowercase variables are also detected.

```bash
BB_PROXY_MODE="mihomo"
BB_HTTP_PROXY="http://127.0.0.1:7890"
BB_SOCKS_PROXY="socks5://127.0.0.1:7891"
```

After editing, source `env.sh` again. A listening mihomo service does not enable
proxying by itself; the dashboard distinguishes `listener` from `applied`.

## Platform Identity

Set only the username, not passwords or API tokens:

```bash
BB_H1_USERNAME="your-hackerone-username"
```

It is required when the selected platform is `hackerone` and informational for
other platforms. Butian, generic VDP, standalone CTF, and local lab overlays do
not inherit HackerOne request-identification rules.

## OTP Mail Adapter

OTP retrieval is an optional L5 provider. A compatible installation supplies:

```text
command: mail-otp
config:  $HOME/.local/share/pentest-mail/config.env (mode 600)
probe:   mail-otp --test
```

The stack does not define provider-specific mailbox credential fields because
Gmail App Password, IMAP, and OAuth deployments differ. Install the adapter in
`$HOME/.local/bin`, keep its credentials only in the config path above, and run:

```bash
chmod 600 "$HOME/.local/share/pentest-mail/config.env"
bb-stack status --profile web
bb-stack status --profile web --check-external
```

Status checks command presence and file mode locally. The external check calls
only `mail-otp --test` and suppresses its output.

## File Delivery

Set a base HTTP or HTTPS origin without a take code, token, query, or path:

```bash
BB_FILECODEBOX_URL="https://filebox.example"
```

Local status validates the URL shape and `curl` provider. With
`--check-external`, it requests the configured `/health` endpoint through the
selected proxy mode. The displayed endpoint is reduced to scheme, host, and
port.

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

Status checks installed state; update discovery remains a separate read-only
operation so it never slows normal launch or changes the machine implicitly:

```bash
bb-stack updates check --all
```

Stage, validate, promote, and roll back through the contracts in `UPDATES.md`.
