# Secrets And Local State

- Never store passwords, cookies, API tokens, private keys, mailbox credentials,
  or production JWTs in Prompt, Git, reports, screenshots, or shared archives.
- Store controlled test-account notes in `notes/LAB-CREDS.local.md` with mode
  600. Store session material in separate ignored files.
- Put machine-local identity and service origins in `$BB_CONFIG_HOME/config.env`
  through `bb-stack configure`. The generated environment parses values as
  data and never sources the editable config as shell code.
- Keep mailbox automation credentials only in
  `$HOME/.local/share/pentest-mail/config.env` with mode 600. Use hidden or
  stdin secret input; never pass a mailbox password as a command argument.
- Redact evidence before packaging. A reviewer package must contain only the
  relevant issue and paths that exist inside that package.
- Treat third-party MCP/Skill updates as code changes: pin, review, validate,
  then install.
- Portable exports contain only the explicit non-secret allowlist. Inspect them
  before transfer; keep Engagements and secrets in separate encrypted backups.
