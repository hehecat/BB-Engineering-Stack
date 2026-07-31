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
- L2 profile YAML: Prompt composition and L4/L5 profile selection.
- `engagement.yaml`: canonical current work-unit control state.
- `04-L4-Skills/skills.yaml`: Skill inventory and source directory.
- `05-L5-MCP-CLI/capabilities.yaml`: provider/capability mapping.
- `00-L0-Runtime/config/upstreams.yaml`: verified update channels and pins.

Generated Prompt and MCP files live under `$BB_CONFIG_HOME/generated`. Runtime
dependencies live under `.runtime`. Neither is committed.

## Prompt Composition

Append profile:

```text
Claude native system Prompt + L1 personal + L2 workflow + platform + mode
```

Replacement profile:

```text
L1 replacement runtime + L1 personal + L2 workflow + platform + mode
```

Fragments are unique and token-budgeted. `bb-claude` passes exactly one Prompt
flag. Persistent Keysmith deployment is restricted to replacement profiles to
avoid silently converting append behavior into replacement behavior.
