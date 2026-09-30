# Stack Source Repository

This repository builds a portable Claude Code security workflow. Keep changes
inside the L0-L5 owner directory. Do not place engagement data, credentials,
tokens, cookies, recon output, or generated MCP files in source control.

Use `$HOME`, `$BB_STACK_ROOT`, `$BB_WORK_ROOT`, and `$BB_CONFIG_HOME` in source.
Runtime dependencies belong under `.runtime/`; generated Prompt and MCP state
belongs under `$BB_CONFIG_HOME/generated`. Never commit either.
Run `99-Verification/scripts/run-all.sh` after changes.
