# Secrets And Local State

- Never store passwords, cookies, API tokens, private keys, mailbox credentials,
  or production JWTs in Prompt, Git, reports, screenshots, or shared archives.
- Store controlled test-account notes in `notes/LAB-CREDS.local.md` with mode
  600. Store session material in separate ignored files.
- Put machine-local identity and service URLs in `$BB_CONFIG_HOME/config.env`.
- Keep mailbox automation credentials only in
  `$HOME/.local/share/pentest-mail/config.env` with mode 600. Use hidden or
  stdin secret input; never pass a mailbox password as a command argument.
- Redact evidence before packaging. A reviewer package must contain only the
  relevant issue and paths that exist inside that package.
- Treat third-party MCP/Skill updates as code changes: pin, review, validate,
  then install.
