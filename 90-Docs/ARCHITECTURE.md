# Architecture

## Ownership

| Layer | Owns | Must not own |
| --- | --- | --- |
| L0 Runtime | bootstrap, PATH, proxy, launch, deployment | targets, attack knowledge |
| L1 Global Prompt | short personal execution behavior | platform policy, payloads |
| L2 Workflow Profiles | workflow, platform, mode, Prompt composition | live state, secrets |
| L3 Engagement State | scope, lifecycle, evidence references, handoff | shared tooling source |
| L4 Skills | routing and specialist knowledge | session lifecycle authority |
| L5 MCP/CLI | capabilities, providers, health checks | workflow policy |

Keysmith crosses L0-L2 only as an optional persistent deployment backend. It
does not own Prompt text and does not manage Engagements, Skills, or MCP.

Update governance belongs to L0. It reads L4/L5/runtime inventories, stages
candidates under `.runtime`, and may modify a layer only after that layer's
contracts pass. It does not add attack knowledge or change workflow policy.

## Sources Of Truth

- `stack.yaml`: roots, defaults, registry locations, pinned Keysmith source.
- Source-root `CLAUDE.md`: conversational first-run setup, maintenance, and
  handoff into the configured workspace.
- Workspace `CLAUDE.md`: natural-language task classification, stack operations,
  route invocation, and agent-owned repair.
- L2 profile YAML: Prompt composition and L4/L5 profile selection.
- `engagement.yaml`: canonical current work-unit control state.
- `04-L4-Skills/skills.yaml`: Skill inventory and source directory.
- `05-L5-MCP-CLI/capabilities.yaml`: provider/capability mapping.
- `00-L0-Runtime/config/upstreams.yaml`: verified update channels and pins.
- `00-L0-Runtime/config/data-catalog.yaml`: data repositories, revisions,
  bundles, sentinels, and Profile requirements.

Generated strict-launch Prompt and MCP files live under
`$BB_CONFIG_HOME/generated`. Bootstrap also renders a small project router,
project MCP baseline, and machine-local Claude settings into the user-selected
`$BB_WORK_ROOT`. Runtime dependencies live under `.runtime`. None are committed
to this source repository.

## Natural Claude Entry

Claude may first be opened in the cloned source repository. Its root
`CLAUDE.md` treats that tree as stack source, bootstraps the minimal control
plane, preserves existing state, and transfers target work to the configured
workspace. The user does not need to choose a domain Profile during setup.

`cd "$BB_WORK_ROOT" && claude` loads the generated project `CLAUDE.md`. The
router first classifies Bug Bounty, authorized assessment, CTF, standalone
analysis, or Lab, then selects Web/API, Browser-JS, Android, iOS, Reverse,
network, cloud, LLM/agent, or source intent and calls `bb-stack workspace route`.
That command creates or resumes the isolated
Engagement, renders its exact L2 Prompt, reports the ordered Skill route, and
returns the four L3 state files to read.

The router owns control-plane commands. It runs returned bootstrap and repair
actions, verifies them, and continues into domain work. It asks one compact
question only for an unresolved target/outcome, ambiguous continuation, written
Scope, or external prerequisite. Environment and personal-integration requests
are handled as stack operations and do not create Engagements.

The project `.mcp.json` intentionally contains no domain MCP. MCP servers are
selected when Claude starts, so strict per-profile MCP composition uses
`bb-stack launch`. This preserves a simple default entry without exposing
Playwright or DevTools schemas to unrelated network, cloud, source, or mobile
tasks. Browser work uses the Chrome DevTools CLI in this natural entry and the
matching MCP provider in a strict Profile launch. `bb-stack browser start` owns an
Engagement-local Chromium profile and exposes one loopback CDP endpoint to both.

## Prompt Composition

L2 is a composition matrix, not a linear inheritance tree:

```text
workflow policy (BB | assessment | CTF | analysis | lab)
+ domain method (Web | mobile | network | cloud | LLM | source | reverse | Browser-JS)
+ platform overlay (HackerOne | Butian | generic VDP | authorized assessment | standalone)
+ active mode (interactive | continuous)
```

Every runtime Profile selects exactly one value from each applicable axis.
Cross-domain evidence can load an optional Skill, but it does not switch the
workflow, platform, state tree, or MCP Profile. This preserves useful linkage
without policy leakage.

Append profile:

```text
Claude native system Prompt + L1 personal + L2 workflow + optional domain + platform + mode
```

Replacement profile:

```text
L1 replacement runtime + L1 personal + L2 workflow + optional domain + platform + mode
```

Fragments are unique and token-budgeted. `bb-claude` passes exactly one Prompt
flag. Persistent Keysmith deployment is restricted to replacement profiles to
avoid silently converting append behavior into replacement behavior.

## Evaluation Boundary

Static evaluation verifies all Prompt fragments, state-resume names, token
budgets, orchestrator requirements, domain routing, and L4/L5 references.
Real-Agent evaluation uses a generated local Engagement with unique markers,
allows only Claude read/write tools, prohibits network work, and scores Scope,
HANDOFF, STATUS, next-action, the complete Skill route, and artifact placement.
The Web profile also applies the current `bb-orchestrator` snapshot to a local
decision fixture and scores candidate-asset handling, high-signal Lead choice,
proof labels, root-cause clustering, action counts, canonical logs, and a
synthetic secret canary. It also scores that an early high-signal branch may
expand immediately while unfinished baseline stages remain incomplete and are
resumed afterward.
The Browser-JS profile uses a separate local decision fixture to score runtime
observation, narrow call-chain selection, Hook-before-breakpoint behavior,
minimal environment reconstruction, differential validation, and outcome-led
deliverable selection.
The router Agent smoke classifies 14 natural-language tasks across the full
matrix, including a non-Engagement stack operation, without naming an internal
Profile. Static contracts also reject
assessment/CTF/analysis policy leakage and required cross-domain handoffs.
Prompt and evaluation-contract SHA256 values prevent a prior pass from
validating changed behavior. The contract digest includes the routed Skill
trees, fixture builder, and scorer, so updating an orchestrator, terminal
profile Skill, fixture, or scoring logic invalidates the prior result.
