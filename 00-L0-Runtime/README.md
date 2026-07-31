# L0 Runtime

L0 owns bootstrap, pinned Python/Node dependencies, portable Linux Node/Go
fallbacks, PATH rendering, tool installers, launchers, the Keysmith adapter,
and staged update governance.

Run the dependency-light entrypoint first on a new machine:

```bash
./00-L0-Runtime/bin/bootstrap --profile ctf-web
source "$HOME/.config/bb-stack/env.sh"
```

Machine output is written only to `.runtime/`, `$BB_CONFIG_HOME`, and
`$HOME/.local/bin`. `config.env` is mode 600 and is never copied into source.

Use `bb-stack updates check --all` for a read-only dependency audit. Candidate
updates are isolated under `.runtime` and require separate validate and promote
commands; see `90-Docs/UPDATES.md`.
