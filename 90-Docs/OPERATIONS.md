# Engagement Operations

## Create And Resume

Normal use starts from the selected workspace and does not expose Profile names:

```bash
cd "$BB_WORK_ROOT"
claude
```

Describe a new target, artifact, or continuation in natural language. The
project router creates or resumes the Engagement and loads its Prompt and state.
When you are not sure which command fits the situation, run `bb-stack guide`.
Use the commands below only for explicit control or strict reproduction.

```bash
bb-stack new SLUG TARGET --workflow ctf --platform standalone-ctf
bb-stack status --profile ctf-web --engagement SLUG --strict
bb-stack engagement validate SLUG
bb-stack launch --profile ctf-quick --engagement SLUG
```

The launcher changes its working directory to the Engagement. Claude reads
`engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md` before
selecting work.

For Bug Bounty Recon:

```bash
bb-recon status SLUG --json
bb-recon run SLUG --json
bb-recon resume SLUG --json
bb-recon expand SLUG --area AREA --target TARGET --reason REASON --signal SIGNAL_ID --json
bb-recon close SLUG --reason REASON --accept-gap GAP_ID
```

Optional public search enrichment is available through Exa, Tavily, and Brave
Search. Set only the provider key needed for the local run (`EXA_API_KEY`,
`TAVILY_API_KEY`, or `BRAVE_SEARCH_API_KEY`) and rerun `organization-assets`.
The resulting URLs remain reviewable scope candidates and are not activated
automatically.

`dns-active` uses the system resolver unless `BB_DNS_RESOLVERS` names others. On
a network that intercepts DNS (fake-ip proxies, captive portals) every
brute-force word resolves and the stage times out on phantoms; a DNS-over-HTTPS
resolver rides port 443 and survives that. See `90-Docs/CONFIGURATION.md`.

`close` also accepts repeated `--accept-signal` and `--accept-candidate` IDs.
Read `recon/coverage.json` before acknowledging any limit, and note that an
unfinished pipeline is not a limit you get to close: `bb-stack coverage SLUG`
reports the stage rollup, and `--gate --max-incomplete-stages N` refuses to
accept one.

For Bug Bounty, use profile `web` with `bb-interactive` or `bb-continuous`.
`bb-stack status --profile web --engagement SLUG` derives the platform and mode
from `engagement.yaml`, then checks the matching personal requirements.
Authorized non-BB work uses the `assessment` workflow and one domain Profile;
standalone reconstruction uses `analysis`. Optional cross-domain Skills do not
change the active workflow, Scope, platform overlay, or MCP composition.

## Lifecycle

```bash
bb-stack engagement checkpoint SLUG
bb-stack engagement pause SLUG --reason 'external dependency'
bb-stack engagement resume SLUG
bb-stack engagement close SLUG --reason 'completed'
bb-stack engagement reopen SLUG
```

Before pausing or switching computers, update evidence references, exact next
action, STATUS, HANDOFF, then checkpoint YAML. Keep credentials only in ignored
local files with mode 600.

## Before Closing Or Handing Off

Treat close and handoff as a convergence decision, not just a state change. Run
`bb-stack coverage SLUG --gate ...` with the thresholds that mean "done" for this
engagement, and keep its output -- the PASS/FAIL lines plus any listed `uncovered`
hosts, `unmatched` hosts, or `unfinished recon stages` -- with STATUS and HANDOFF.
Work what it names, or record why each item stays open. Include
`--max-incomplete-stages 0` when the engagement must be *surveyed* and not merely
reported on: the asset thresholds cannot see a pipeline that never ran. See
`90-Docs/COVERAGE.md` for the thresholds and exit codes: a gate that was not run
is not a gate that passed.

## Continuous Mode

Use an Engagement created with `--mode continuous` and launch
`bb-continuous`. Specialist Skill pivot rules close one lead; they do not close
the Engagement. SHIP starts when the work reaches that phase or the user asks
for delivery.

## Unified Status

Run the local dashboard before launch, after configuration changes, and after
moving the stack to another machine:

```bash
bb-stack status --profile ctf-web
bb-stack status --profile web --platform hackerone --probe-mcp
bb-stack status --profile web --engagement SLUG --strict --json
```

`--strict` returns nonzero only for required failures. Missing optional OTP,
file delivery, Codex Skills, or Keysmith deployment remains visible without
blocking an unrelated CTF workflow. `--check-external` is opt-in because it
contacts configured external services.

## Agent Evaluation

```bash
bb-stack eval contracts
bb-stack eval agent --profile ctf-quick
bb-stack status --profile ctf-web --require-agent-eval --strict
```

The contract suite makes no model call. The Agent suite creates a synthetic
Engagement under `$BB_CONFIG_HOME/evaluations`, allows only local read/write,
and stores a scored report without target data. Status marks a report stale
when the stack version, rendered Prompt digest, routed Skill content, or
evaluation contract changes. Without
`--require-agent-eval`, missing or stale evaluation is visible but optional.

## Machine Configuration And Handoff

```bash
bb-stack configure
source "$BB_CONFIG_HOME/env.sh"
bb-stack portable export "$HOME/bb-stack-portable.json"
bb-stack portable inspect "$HOME/bb-stack-portable.json"
```

On a destination machine, bootstrap first, preview with `portable import`, then
apply with `--yes`. Restore Engagement content from its separate backup and use
the emitted secret checklist for local-only integrations.
