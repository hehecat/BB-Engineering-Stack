# BB Stack Workspace Router

This directory is a security-work workspace, not an Engagement. Keep target
data under `engagements/<slug>/`; use `inbox/` only for unclassified input.

## User Experience Contract

Conversation is primary. Operate `bb-stack`, MCP, and CLI tools yourself. Do not
ask users to choose Profiles, routes, repair commands, directories, or sessions.

Inspect local config, files, Engagements, and tool status before asking.
Ask one compact question only when an answer materially changes the next safe
action, for example:

- the target, artifact, requested outcome, or continuation is genuinely
  ambiguous;
- multiple active Engagements plausibly match an unnamed continuation;
- a real-target task needs Scope, rate limits, credentials, an account, a
  device, or another unavailable external prerequisite;
- a Browser-JS or standalone-analysis task lacks an acceptance criterion that
  changes the deliverable.

Do not ask the user to choose an internal Profile, tool, slug, output directory,
or phase. Infer them. CTF, standalone analysis, and lab work uses exempt
authorization. Bug Bounty and assessment work requires a recorded source and
`authorization.status=verified` before active target traffic. Never invent a
source or infer authorization from access or ownership. Pending work permits
only local inspection and Scope preparation. Related assets remain candidates
until written rules cover them.

Environment, proxy, identity, mailbox, FileCodeBox delivery, managed data,
update, and migration requests are stack operations, not Engagements. Inspect
status, make
and verify the machine-local change, then report it. Personal integrations
remain optional.

For FileCodeBox delivery, use `filecodebox-upload <path> --json` after checking
the configured delivery status. Keep tokens on stdin with `--token-stdin`.

## Route Before Acting

Infer each route from the user's words and target.

| User intent | Route kind | Default platform |
| --- | --- | --- |
| CTF Web, Web challenge, HTTP/API challenge | `ctf-web` | `standalone-ctf` |
| CTF APK/XAPK/AAB/JAR/AAR challenge | `ctf-android` | `standalone-ctf` |
| CTF native binary, firmware, or bytecode challenge | `ctf-reverse` | `standalone-ctf` |
| Bug Bounty, VDP, or ordinary Web/API penetration target | `web` | `generic-vdp` |
| Contracted or explicitly scoped Web/API security assessment | `web-assessment` | `authorized-assessment` |
| Android application penetration test or mobile security audit | `android-assessment` | `authorized-assessment` |
| Android decompilation, algorithm recovery, or behavior analysis only | `android-analysis` | `standalone-analysis` |
| Authorized native binary, firmware, or component security assessment | `reverse-assessment` | `authorized-assessment` |
| iOS/IPA application penetration test or mobile security audit | `ios-assessment` | `authorized-assessment` |
| Native binary, firmware, or bytecode analysis without a CTF goal | `reverse-analysis` | `standalone-analysis` |
| Internal network, CIDR, Active Directory, or service assessment | `network-assessment` | `authorized-assessment` |
| AWS, Azure, GCP, IAM, storage, or cloud posture assessment | `cloud-assessment` | `authorized-assessment` |
| LLM, RAG, agent, MCP, memory, or prompt-injection assessment | `llm-assessment` | `authorized-assessment` |
| Source repository, SAST, IaC, container, dependency, or threat-model review | `source-audit` | `authorized-assessment` |
| Browser JavaScript analysis, deobfuscation, request signing or encryption reconstruction, runtime hooks, page behavior modification, extensions, or user scripts | `browser-js` | `standalone-analysis` |
| Local reproduction fixture or controlled lab | `lab` | `local-lab` |

Override the Web platform only when the user names it: HackerOne uses
`hackerone`; Butian or BuTian uses `butian`; another VDP uses `generic-vdp`.
Use continuous mode when the user explicitly asks to keep testing until told to
stop; otherwise use interactive mode.

Intent takes precedence over file type: a Web security target stays `web` or
`ctf-web`; use `browser-js` when understanding or modifying client JavaScript is
the requested outcome. Do not assume that a `browser-js` task must produce a
user script. For an APK, choose the workflow from the requested outcome: CTF
solve, authorized assessment, or standalone analysis. The legacy route kinds
`android` and `reverse` remain valid only for resuming older CTF Engagements.

Keep the selected workflow stable. A Browser-JS lead inside Bug Bounty, an API
lead inside mobile testing, or a cloud identity lead inside a source review is
a specialist handoff inside the current Engagement when the written Scope
covers it; it is not a reason to import another Profile's policy. Route a new
Engagement only when the primary objective or authorization boundary changes.

Before the first domain action, run:

```bash
bb-stack workspace route --kind KIND --target TARGET [--slug SLUG] \
  [--platform PLATFORM] [--mode interactive|continuous] \
  [--authorization-status verified --authorization-source SOURCE]
```

For `continue SLUG`, omit `--target` and route with `--slug SLUG`. For an
unnamed continuation, run `bb-stack engagement list --json`; select it only
when exactly one plausible active work unit exists, otherwise ask one compact
question.

Read every path returned in `prompt_file` and `state_files` before testing.
Treat the returned `engagement` directory as the active working directory for
all reads, commands, evidence, scripts, reports, and checkpoints. Run the
returned repair commands yourself when required components are missing, then
rerun the route. Diagnose and retry recoverable failures; ask only when an
external prerequisite or unresolved local-file conflict blocks progress. Use
the ordered `skill_route`; add only the specialist for the current lead. Keep
discovered assets as candidates until written Scope matches them. For protected
work, confirm lifecycle is `active` and authorization is `verified`. A
`DESCRIPTION` repair requires the real written source; never fabricate it. Use
the reported `bb-stack data ensure` action for missing managed data. After
routing, start the first permitted useful action instead of ending with status.
Bug Bounty Recon: run `bb-recon status`, then use its structured `run`,
`resume`, `expand`, or `close` action.

## Session Discipline

- Stay in the selected Engagement until the user changes target or task.
- Resume from `SESSION-HANDOFF.md`, `STATUS.md`, and `bb-recon status`; do not
  restart completed stages.
- Keep large output in files and record material evidence paths and next action.
- Never place target recon, credentials, tokens, APK output, or reports in this root.
- `.mcp.json` intentionally has no domain MCP. For browser work in a normal
  session run the route result's `browser_start` command and use the
  managed `chrome-devtools` CLI. Profile-specific MCP isolation remains
  available through the returned `strict_launch` command.
- Do not deploy or modify Keysmith unless the user explicitly requests it.
