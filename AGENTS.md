# Stack Source Repository

This repository builds a portable Claude Code security workflow. Keep changes
inside the L0-L5 owner directory. Do not place engagement data, credentials,
tokens, cookies, recon output, or generated MCP files in source control.

Use `$HOME`, `$BB_STACK_ROOT`, `$BB_WORK_ROOT`, and `$BB_CONFIG_HOME` in source.
Generated machine paths belong under `.runtime/` or `05-L5-MCP-CLI/generated/`.
Run `99-Verification/scripts/run-all.sh` after changes.
