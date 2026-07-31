# Verification

```bash
./99-Verification/scripts/run-all.sh
./99-Verification/scripts/fresh-machine.sh
./99-Verification/scripts/keysmith-smoke.sh
./99-Verification/scripts/claude-smoke.sh
```

`run-all.sh` performs contracts, lifecycle tests, Prompt budgets, Skill
frontmatter checks, strict YAML and MCP uniqueness tests, update-inventory and
candidate-isolation tests, first-party mail-otp config/MIME/Fake-IMAP contracts,
unified-status redaction and profile tests, strict CTF/Web doctors, and a real
Playwright MCP handshake when runtime dependencies exist. Fresh-machine
verification also requires `bb-stack status --strict` and the `mail-otp`
wrapper to pass in an isolated HOME. The other scripts isolate HOME and work
roots. Claude smoke requires working Claude authentication and consumes one
small model request.
