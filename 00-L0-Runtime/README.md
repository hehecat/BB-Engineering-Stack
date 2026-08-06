# L0 Runtime

L0 owns bootstrap, pinned Python/Node dependencies, portable Linux Node/Go
fallbacks, PATH rendering, tool installers, launchers, the Keysmith adapter,
and staged update governance.

Run the dependency-light entrypoint first on a new machine:

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web \
  --work-root "$HOME/BB-Workspaces"
source "$HOME/.config/bb-stack/env.sh"
bb-stack status --profile ctf-web --strict
```

Machine output is written only to `.runtime/`, `$BB_CONFIG_HOME`, and
`$HOME/.local/bin`, plus the user-selected `$BB_WORK_ROOT`. The work-root value
is not fixed; the displayed path is only the recommended default. `config.env`
is mode 600 and is never copied into source.

Bootstrap renders the natural Claude entry in the work root. Inspect or refresh
it with `bb-stack workspace status` and `bb-stack workspace init`.

Use `bb-stack updates check --all` for a read-only dependency audit. Candidate
updates are isolated under `.runtime` and require separate validate and promote
commands; see `90-Docs/UPDATES.md`.

`bb-stack status` is the unified read-only dashboard. It audits the resolved
roots, runtime, Prompt, current Engagement, Skills, MCP/CLI, proxy environment,
personal integrations, and optional Keysmith deployment without printing
configured passwords or tokens.

Use `bb-stack configure` for non-secret machine options. It parses
`config.env` as literal assignments, writes it atomically with mode 600, and
regenerates `env.sh`; generated shell code never sources the editable config
file. `bb-stack portable` exports and restores the safe subset without old
absolute paths or credentials.

`bb-stack eval contracts` checks every L2/L4/L5 route without a model call.
`bb-stack eval agent` runs a bounded Sonnet startup fixture in an isolated work
unit and records its Prompt digest and scored result under `$BB_CONFIG_HOME`.
Pinned archive-tree and Debian-package installers provide JADX and Radare2 when
the distribution repository does not.

Bootstrap also installs the first-party `mail-otp` compatibility command. Use
`bb-stack mail configure` and `bb-stack mail test`; mailbox credentials remain
outside the repository in a mode-600 local config.

The first-party `bb-recon` wrapper exposes the scoped Recon state machine to
Agents without requiring them to reconstruct Provider command chains.
