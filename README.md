# BB Engineering Stack

[简体中文](README.zh-CN.md) | English

A portable Claude Code workflow for security work. After one initialization,
the primary interface is normal conversation: the user provides a target or
artifact and an objective; Claude selects the workflow, domain, Prompt, Skills,
MCP/CLI capabilities, Scope state, and evidence directory.

It covers Web/API, CTF, Bug Bounty/VDP, Android, iOS, Browser JavaScript,
reverse engineering, network/AD, cloud, LLM/agent, source, IaC, container, and
supply-chain work.

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
existing machine first and ask one compact question only for decisions I must make.
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
Assess inbox/product.apk as an authorized Android application
Decompile inbox/library.apk and reconstruct its signing algorithm
Assess inbox/service.elf as an authorized native component
Analyze https://app.example request signing and deliver a reusable Node module
Assess the authorized 10.20.0.0/24 network and Active Directory
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
3. Read the routed Prompt, Scope, STATUS, and HANDOFF before domain work.
4. Install or repair missing capabilities itself and verify them.
5. Load only the orchestrator and specialist needed for the active lead.
6. Keep target artifacts and state outside the source repository.
7. Treat setup, proxy, identity, mailbox, delivery, and updates as stack
   operations rather than target Engagements.

Claude inspects local state before asking. It asks one compact question only
when missing target intent, ambiguous continuation, written Scope, credentials,
a device, an account, or a material acceptance criterion blocks the next
action. It never asks the user to choose an internal Profile. CTF and local
analysis do not trigger repeated authorization questions. Without broader
written Scope, an ordinary remote target is limited to the exact supplied
target and related assets remain candidates.

## Personal Configuration

Optional integrations do not block first use. Ask Claude to configure them when
needed:

```text
Use local mihomo on HTTP 7890 and SOCKS 7891
Set my HackerOne username
Use my FileCodeBox instance for delivery

Upload a delivery artifact with `bb-stack filecodebox upload ./artifact.zip --json`.
The command uses FileCodeBox's `POST /share/file/` API and returns the retrieval code.
Configure the lab mailbox for OTP retrieval
Check pinned Skill, MCP, and tool updates without upgrading
```

Secrets remain in machine-local restricted files, not Prompts, Git, reports, or
normal chat. Keysmith remains opt-in and is not modified during ordinary work.

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
| L3 | `03-L3-Engagement-State/` | Scope, status, evidence index, handoff |
| L4 | `04-L4-Skills/` | orchestrators and specialist knowledge |
| L5 | `05-L5-MCP-CLI/` | browser, HTTP, mobile, reverse, and other execution |

Prompt owns policy and continuity, Skills provide methodology, MCP/CLI executes,
and files preserve cross-session state. Cross-domain leads may call another
specialist without silently changing workflow, Scope, or report policy.

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
