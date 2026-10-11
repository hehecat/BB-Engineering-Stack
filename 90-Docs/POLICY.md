# Tool-Call Policy

Engagement-level gating for our own MCP servers. The host harness gates tool
calls in coarse presets, and retuning those presets means patching the harness;
our servers are ours to gate, so interception lives here, at the MCP layer.

## Scope: MCP Layer, Not Harness Permissions

- This policy decides whether **our MCP server** actually runs a tool call the
  client sent. It is not the host harness permission model.
- The two coexist, outermost first: the harness still decides which tools an
  agent may call at all, and whether to prompt a human. Only if the call reaches
  our server does this policy run.
- Never treat one as a substitute for the other. A harness that allows
  everything still hits this gate; a policy `bypass` mode still cannot make the
  harness offer a tool it does not offer.
- `policy.yaml` lives at `<engagement>/policy.yaml`. A read command of the driver
  is `bb-stack policy show <SLUG>`; a dry run of one call is
  `bb-stack policy check <SLUG> --tool <NAME> [--arg KEY=VALUE]`.
- Start from `90-Docs/policy.yaml.example` (commented, every key validated by
  `ToolPolicy.from_mapping`); copy it in and delete what you do not use. It is
  deliberately not under `03-L3-Engagement-State/templates/`, which holds only
  files the runtime itself copies.

## Evaluation: Four Phases, Order Is Semantics

1. **Deny rules -- absolute.** First match wins; no mode and no allow rule can
   override a deny.
2. **Mode short-circuit.** `bypass` allows everything, `read-only` denies every
   non-read-only tool, `default` decides nothing and falls through.
3. **Allow rules / read-only auto-pass.** First matching allow rule wins;
   otherwise a read-only tool is allowed.
4. **Interactive confirmation.** When nothing above decided, the call goes to a
   caller-injected callback. With no callback -- or any answer that is not an
   explicit allow -- the call is **denied (fail-closed)**.

## Default Posture

- Shipped `deny` and `allow` are **empty on purpose**. The default posture is
  "read-only tools auto-pass, everything else is asked" -- never "allow
  everything".
- In `default` mode a read-only tool (matching the shipped patterns plus any
  `read_only` entries) runs without confirmation. Everything else reaches phase
  4 and, with no channel, is denied.
- The traffic MCP server folds its own tools into the read-only set: every tool
  it exposes only reads engagement state, so its calls pass under the default
  posture instead of dead-ending at phase 4.

## Fail-Closed

- A missing `policy.yaml` means the defaults, never a refusal to serve. An
  Engagement that cannot be resolved also falls back to the defaults.
- A `policy.yaml` that exists but cannot be read or parsed is different: the
  server logs one line and **denies every call**. A broken rule set must not
  silently open the gate.
- Any unexpected failure while evaluating a call is logged and denied with the
  reason on stderr; policy trouble never crashes the server.
- `ask` with no interactive channel is a denial. A stdio MCP server has no human
  to ask, so an unanswered `ask` resolves to deny and says so.

## Rule DSL

Top-level keys, all optional: `mode` (`read-only` | `default` | `bypass`),
`read_only`, `deny`, `allow`. Unknown keys are rejected.

```yaml
mode: default          # read-only | default | bypass
read_only:             # extra read-only tool patterns (defaults kept)
  - "mcp__traffic__*"
deny:                  # evaluated first, first match wins
  - "dangerous(...)"                 # string form: tool-name pattern
  - tool: "write_file"               # mapping form
    when:                            # optional argument conditions (ANDed)
      arg_contains: {path: "/etc/"}
    message: "writes outside the engagement"
    updated_input: {force: null}     # null deletes the key
allow:                 # evaluated after deny, first match wins
  - tool: "read_flow"
    when: {arg_present: [id]}
```

- Tool-name patterns: `"*"` matches every tool; `"Name(...)"` matches `Name` and
  any tool name *starting* with `Name`; anything else is an fnmatch-style glob
  (`?`, `*` inside the name).
- Argument conditions (all conditions in one `when` are ANDed):
  - `arg_equals` -- `{key: value}`: `arguments[key] == value`
  - `arg_contains` -- `{key: substring}`: substring of `str(arguments[key])`
  - `arg_in` -- `{key: [values]}`: `arguments[key]` is in the list
  - `arg_present` -- `[key, ...]`: key exists with a non-empty value
- `updated_input` rewrites the arguments when a matching allow rule fires. The
  rewrite is applied **and reported** in the tool result (under `policy`), never
  swapped in silently. The schema is
  `05-L5-MCP-CLI/schema/policy.schema.json`.

## Checklist

- [ ] Start from the default posture; add a `deny` rule only for a call that must
      never run, and make its `message` the reason a human needs.
- [ ] Prefer narrowing with `when` over denying a whole tool.
- [ ] Reach for `mode: bypass` only for a throwaway lab, never a live target.
- [ ] Remember `deny` beats `bypass`: a deny rule still fires in bypass mode.
- [ ] Validate a new file against `05-L5-MCP-CLI/schema/policy.schema.json`
      before trusting it, then confirm with `bb-stack policy show <SLUG>`.
