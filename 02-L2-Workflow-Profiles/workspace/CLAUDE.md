# BB Stack Workspace Router

This directory is a security-work workspace, not an Engagement. Keep target
data under `engagements/<slug>/`; use `inbox/` only for unclassified input.

## Route Before Acting

For each new security task, infer the route from the user's words and supplied
target. Do not ask the user to choose an internal Profile.

| User intent | Route kind | Default platform |
| --- | --- | --- |
| CTF Web, Web challenge, HTTP/API challenge | `ctf-web` | `standalone-ctf` |
| Penetration test, Bug Bounty, VDP, Web/API target | `web` | `generic-vdp` |
| APK/XAPK/AAB/JAR/AAR or Android reverse engineering | `android` | `standalone-ctf` |
| Native binary, firmware, bytecode, or general reverse engineering | `reverse` | `standalone-ctf` |
| Local reproduction fixture or controlled lab | `lab` | `local-lab` |

Override the Web platform only when the user names it: HackerOne uses
`hackerone`; Butian or BuTian uses `butian`; another VDP uses `generic-vdp`.
Use continuous mode when the user explicitly asks to keep testing until told to
stop; otherwise use interactive mode.

Before the first domain action, run:

```bash
bb-stack workspace route --kind KIND --target TARGET [--slug SLUG] \
  [--platform PLATFORM] [--mode interactive|continuous]
```

For `continue SLUG`, omit `--target` and route with `--slug SLUG`. For an
unnamed continuation, run `bb-stack engagement list --json`; select it only
when exactly one plausible active work unit exists, otherwise ask one compact
question.

Read every path returned in `prompt_file` and `state_files` before testing.
Treat the returned `engagement` directory as the active working directory for
all reads, commands, evidence, scripts, reports, and checkpoints. Run the
returned repair commands when required components are missing, then rerun the
route command. Use the ordered `skill_route`; add only the specialist Skill for
the current lead.

## Session Discipline

- Stay in the selected Engagement until the user changes target or task.
- Resume from `SESSION-HANDOFF.md` and `STATUS.md`; do not restart recon by default.
- Keep large output in files and record material evidence paths and next action.
- Never place target recon, credentials, tokens, APK output, or reports in this root.
- `.mcp.json` is the small project-wide Headless MCP baseline. Profile-specific
  MCP isolation remains available through the returned `strict_launch` command.
- Do not deploy or modify Keysmith unless the user explicitly requests it.
