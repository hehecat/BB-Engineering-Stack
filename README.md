# BB Engineering Stack

[简体中文](README.zh-CN.md) | English

A portable Claude Code workflow for security work. After one initialization,
the primary interface is normal conversation: the user provides a target or
artifact and an objective; Claude selects the workflow, domain, Prompt, Skills,
MCP/CLI capabilities, target state, and evidence directory, then executes
immediately without asking for authorization or confirmation.

It covers Web/API, CTF, Bug Bounty/VDP, Android, iOS, Browser JavaScript,
reverse engineering, binary exploitation (CTF Pwn / memory corruption proof),
network/AD, cloud, LLM/agent, source, IaC, container, and supply-chain work on
Linux (`x86_64`/`arm64`) and macOS (`arm64`/`x86_64` via Homebrew + Xcode CLT).

## Start Once

Install and authenticate Claude Code, then either ask Claude to initialize the
stack:

```bash
git clone YOUR_PRIVATE_REMOTE "$HOME/BB-Engineering-Stack"
cd "$HOME/BB-Engineering-Stack"
claude
```

```text
Initialize this security workflow with the recommended defaults. Inspect the
existing machine, choose sensible defaults for anything ambiguous, and complete
the setup without asking me to confirm each step.
```

The source-root `CLAUDE.md` owns setup, detects existing state, recommends
`$HOME/BB-Workspaces`, performs bootstrap, and verifies the result.

For a deterministic one-command setup:

```bash
./00-L0-Runtime/bin/bootstrap --profile minimal \
  --work-root "$HOME/BB-Workspaces"
```

`minimal` installs the natural-language control plane. Claude installs a domain
Profile only when a routed task needs it.

## Use Conversation

Start Claude from the selected work root:

```bash
cd "$HOME/BB-Workspaces"
claude
```

Examples:

```text
Solve this Web CTF: https://challenge.example
Test https://target.example as a continuous Bug Bounty engagement
Assess inbox/product.apk as an Android application
Decompile inbox/library.apk and reconstruct its signing algorithm
Assess inbox/service.elf as a native component
Analyze https://app.example request signing and deliver a reusable Node module
Assess the 10.20.0.0/24 network and Active Directory
Audit this AWS account's IAM and object storage
Test this RAG agent's prompt-injection, MCP, and memory boundaries
Audit inbox/repository source, IaC, containers, and dependencies
Continue example-bb
Check whether my environment, proxy, Skills, and MCP are ready
```

Users do not need to remember Profile names, route kinds, Engagement commands,
MCP launch modes, or repair commands.

## Agent Contract

The generated workspace `CLAUDE.md` makes Claude:

1. Infer workflow, domain, and platform from intent.
2. Create or resume an isolated `engagements/<slug>/`.
3. Read the routed Prompt, target context, STATUS, and HANDOFF before domain work.
4. Install or repair missing capabilities itself and verify them.
5. Load only the orchestrator and specialist needed for the active lead.
6. Update state and handoff after material progress; in continuous mode it does
   not stop after reporting status.
7. Keep target artifacts and state outside the source repository.
8. Treat setup, proxy, identity, mailbox, delivery, and updates as stack
   operations rather than target Engagements.

Claude inspects local state, fills every default it can infer, and starts the
first concrete action immediately. It never asks for authorization, permission,
scope, consent, or confirmation, and never asks the user to choose an internal
Profile. Discovered related assets are active by default and are recorded in
the Engagement while work continues. A missing file, credential, or device is
worked around where possible and recorded as a dependency, not used as a
stopping point.

## Personal Configuration

Optional integrations do not block first use. Ask Claude to configure them when
needed:

```text
Use local mihomo on HTTP 7890 and SOCKS 7891
Set my HackerOne username
Use my FileCodeBox instance for delivery
Configure the lab mailbox for OTP retrieval
Check pinned Skill, MCP, and tool updates without upgrading
```

Upload a delivery artifact with:

```bash
bb-stack filecodebox upload ./artifact.zip --json
```

The command calls FileCodeBox's `POST /share/file/` API and returns the retrieval
code. If guest uploads are disabled, pass the Bearer token on stdin with
`--token-stdin`.

Secrets remain in machine-local restricted files, not Prompts, Git, reports, or
normal chat. Keysmith remains opt-in and is not modified during ordinary work.

## What You Need To Provide

The minimum input is "a target or file plus the outcome". For a real target, also
provide:

- the program platform, for example HackerOne, Butian, a generic VDP, or a
  contracted assessment;
- any known program rules, exclusions, and rate or side-effect limits (optional context);
- the test account or lab device to use.

## Update The Local Installation

After bootstrap, use the singular update command to check and refresh the Stack:

```bash
bb-stack update --check
bb-stack update
```

Bootstrap records the most recently installed Capability Profile and update
reuses it. When upgrading an older installation without this state, supply the
Profile once, for example `bb-stack update --profile minimal`. Non-refreshing
`--check` and `--dry-run` tolerate local source edits (`--check` may refresh Git
remote metadata); a real refresh rejects modifications to tracked source files,
allows unrelated untracked runtime artifacts, fast-forwards only to the fetched revision, and refuses to
overwrite locally modified Workspace-managed files. Engagements, credentials,
and user-local settings are outside its update target. Source fast-forward and
local refresh are separate transactions; a failed Bootstrap leaves the source
updated and can be retried with `bb-stack update`.

Singular `bb-stack update` updates the Stack source and local installation.
Plural `bb-stack updates` audits, stages, and promotes Skill, MCP, and tool
dependency candidates.

## Storage Boundaries

```text
$BB_STACK_ROOT/                 source, Prompts, Skills, schemas, tests
$BB_WORK_ROOT/
  CLAUDE.md                     natural-language router
  inbox/                        unclassified inputs
  engagements/<slug>/          isolated target state and artifacts
$BB_CONFIG_HOME/                machine-local config and generated state
$BB_DATA_ROOT/                  pinned wordlist and payload repositories
```

No engagement data belongs in the source repository.

## L0-L5

| Layer | Directory | Responsibility |
| --- | --- | --- |
| L0 | `00-L0-Runtime/` | bootstrap, PATH, proxy, runtime, launchers |
| L1 | `01-L1-Global-Prompt/` | language and global operating behavior |
| L2 | `02-L2-Workflow-Profiles/` | workflow/domain/platform Prompts and routing |
| L3 | `03-L3-Engagement-State/` | Target state, status, evidence index, handoff |
| L4 | `04-L4-Skills/` | orchestrators and specialist knowledge |
| L5 | `05-L5-MCP-CLI/` | browser, HTTP, mobile, reverse, and other execution |

Prompt owns policy and continuity, Skills provide methodology, MCP/CLI executes,
and files preserve cross-session state. Cross-domain leads may call another
specialist without silently changing workflow or report policy.

## Operator Documentation

Normal users do not need the CLI lifecycle. These references are for explicit
automation, migration, troubleshooting, or maintenance:

- [Explicit quick start](90-Docs/QUICKSTART.md)
- [Machine configuration](90-Docs/CONFIGURATION.md)
- [Architecture and routing](90-Docs/ARCHITECTURE.md)
- [Engagement operations](90-Docs/OPERATIONS.md)
- [Migration](90-Docs/MIGRATION.md)
- [Updates](90-Docs/UPDATES.md)
- [Data assets](90-Docs/DATA-ASSETS.md)
- [Verification](90-Docs/VERIFICATION.md)
- [Optional Keysmith integration](90-Docs/KEYSMITH.md)

Maintainers run:

```bash
./99-Verification/scripts/run-all.sh
./99-Verification/scripts/audit-dependencies.sh
./99-Verification/scripts/fresh-machine.sh
```

Full-profile network-heavy acceptance uses `full-fresh-machine.sh`; it is not
part of the normal user flow.
