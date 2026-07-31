# Verification

```bash
./99-Verification/scripts/run-all.sh
./99-Verification/scripts/fresh-machine.sh
./99-Verification/scripts/keysmith-smoke.sh
./99-Verification/scripts/claude-smoke.sh
bb-stack eval contracts
bb-stack eval agent --profile ctf-quick
```

`run-all.sh` performs contracts, lifecycle tests, Prompt budgets, Skill
frontmatter checks, strict YAML and MCP uniqueness tests, update-inventory and
candidate-isolation tests, first-party mail-otp config/MIME/Fake-IMAP contracts,
safe archive/deb installer tests, seven-profile Agent contracts, unified-status
redaction and profile tests, strict CTF/Web doctors, and a real
Playwright MCP handshake when runtime dependencies exist. Fresh-machine
verification also requires `bb-stack status --strict` and the `mail-otp`
wrapper to pass in an isolated HOME. The other scripts isolate HOME and work
roots. Claude smoke requires working Claude authentication and consumes one
small model request.

`eval agent` is the stronger behavioral gate. It verifies that real Claude
reads the four L3 state files, preserves exact markers and next action, selects
the expected orchestrator-to-profile Skill route, and writes valid JSON under
`artifacts/`. Use `status --require-agent-eval --strict` to require current
Prompt and evaluation-contract digests.

The unit suite also covers the generated workspace router, a user-selected
work root, the nested Engagement boundary, the project MCP baseline, and
managed-file drift. A release-level plain-Claude check starts `claude` in an
isolated generated workspace and supplies a synthetic Web or APK task without
naming a Profile; the created Engagement must record the expected
`routing.kind` and rendered Profile.
