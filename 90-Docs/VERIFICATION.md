# Verification

```bash
./99-Verification/scripts/run-all.sh
./99-Verification/scripts/fresh-machine.sh
./99-Verification/scripts/keysmith-smoke.sh
./99-Verification/scripts/claude-smoke.sh
./99-Verification/scripts/router-agent-smoke.sh
bb-stack eval contracts
bb-stack eval agent --profile ctf-quick
```

`run-all.sh` performs contracts, lifecycle tests, Prompt budgets, Skill
frontmatter checks, strict YAML and MCP uniqueness tests, update-inventory and
candidate-isolation tests, first-party mail-otp config/MIME/Fake-IMAP contracts,
safe archive/deb installer tests, 17-profile Agent contracts, unified-status
redaction and profile tests, strict CTF/Web doctors, and a real
Playwright MCP handshake when runtime dependencies exist. Fresh-machine
verification also requires `bb-stack status --strict` and the `mail-otp`
wrapper to pass in an isolated HOME. The other scripts isolate HOME and work
roots. Claude smoke requires working Claude authentication and consumes one
small model request.

`eval agent` is the stronger behavioral gate. It verifies that real Claude
reads the four L3 state files, preserves exact markers and next action, selects
the expected Skill route, and writes valid JSON under `artifacts/`. The
`bb-interactive` fixture additionally scores Scope candidate handling, business
Lead priority, proof labels, cross-system chain rejection, root-cause grouping,
minimal action counts, canonical findings path, and synthetic-secret redaction.
Use `status --require-agent-eval --strict` to require current Prompt and
evaluation-contract digests. The contract digest includes the fixture builder
and scorer, so changing evaluation logic also invalidates an earlier pass.

The unit suite also covers the generated workspace router, a user-selected
work root, the nested Engagement boundary, the project MCP baseline, and
managed-file drift. `router-agent-smoke.sh` starts real Claude against an
isolated generated workspace and requires 13 natural-language tasks to select
the expected workflow/domain route and platform without naming a Profile.
