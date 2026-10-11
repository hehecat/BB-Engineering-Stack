# Asset Coverage

A read-only rollup of "how much of this Engagement is still untested?", built by
triangulating facts that already exist on disk.

## Why It Exists

- You can write forty findings and still not know which inventoried hosts were
  never touched. Coverage answers that in one ranking instead of a manual diff.
- It is only a reading of state. `bb_stack.coverage.assess` never creates a state
  file and never writes to the traffic store, so it can run any time without
  changing what it measures.

## Three States (highest evidence wins)

- `concluded` -- a finding row names the asset, or a hypothesis/lead row for it
  reached a terminal state (`validated` or `killed`). The asset was assessed and
  closed one way or the other.
- `touched` -- no conclusion, but at least one traffic flow hit the host.
- `untouched` -- present in the inventory, yet absent from traffic and from any
  finding or terminal lead. `untouched` is the same set reported as `uncovered`.

## Sources (cross-checked)

- `notes/asset-inventory.md` -- the asset list. Canonical shape is a markdown
  table with a `Host` column (hosts in backticks); any `##` section may carry
  one such table. `assets-inventory.md` is accepted as a fallback filename.
- `traffic/flows.db` -- which hosts actually received traffic. Missing or empty
  is not an error, it just means "no traffic evidence".
- `notes/findings-live.md` and `hypotheses.md` -- which assets have a
  conclusion.
- `recon/state.json` -- `coverage_gaps[]`, reported verbatim as `gaps`.

## Ratios (`totals`)

- `ratio` = `concluded / assets` -- the share fully assessed.
- `evidenced_ratio` = `(touched + concluded) / assets` -- the share with any
  evidence, i.e. "has this asset even been touched".
- Both are `0.0` for an empty inventory.
- `uncovered` = the `untouched` count. `traffic_hosts`, `findings`, `leads`,
  `gaps`, and `accepted_gaps` are raw counts of what was read.

## `unmatched` And `accepted_gaps`

- `unmatched` lists hosts seen in traffic but absent from the inventory
  (`{host, flows}`, heaviest first). They are surface you exercised but never
  wrote down: either add them to the inventory or confirm they are out of scope.
- `gaps` are `coverage_gaps[]` from `recon/state.json`, reported verbatim. They
  are scoped to a recon *stage/provider*, not to an asset, so a gap cannot be
  attached to a single host without guessing.
- `accepted_gaps` counts gaps flagged `accepted`. An accepted gap is a declared
  decision to stop, **not** evidence that the asset was exercised -- counting it
  as coverage would inflate the ratio, so the ratio counts only concluded
  assets. `accepted-gap` is deliberately not an asset state.
- `unresolved` lists every non-concluded asset with a plain-language reason.

## Use It As A Driver

- [ ] Run `bb-stack coverage <SLUG>` (or `--json`). The report sorts
      `by_asset` least-covered first: `untouched` before `touched` before
      `concluded`, then by ascending evidence volume, then by host.
- [ ] Read `ratio` for the headline and `evidenced_ratio` to separate "not
      concluded" from "never touched".
- [ ] Work the `unresolved` list top-down: each entry names why it is unresolved
      ("no traffic observed and no conclusion recorded" vs "traffic observed but
      no finding or terminal lead"). That is the queue to push.
- [ ] Reconcile `unmatched` hosts against scope: add them to the inventory or
      mark them out of scope.
- [ ] Re-run after recon or findings land; the report reflects the files as they
      are now.

## Declare Convergence With `--gate`

`coverage` reports; `--gate` decides. Add `--gate` plus at least one threshold to
turn the report into a convergence check with an exit code:

```bash
bb-stack coverage SLUG --gate --max-untouched 0 --min-evidenced-ratio 0.9
bb-stack coverage SLUG --gate --max-unresolved-leads 3 --require-no-unmatched
```

Thresholds (each is inert unless `--gate` is also given):

- `--max-untouched INT` -- pass when `totals.untouched <= INT`: no inventoried asset
  is left never-touched.
- `--min-evidenced-ratio FLOAT` -- pass when `totals.evidenced_ratio >= FLOAT`: the
  share of assets carrying any evidence.
- `--max-unresolved-leads INT` -- pass when `len(unresolved) <= INT`: how many
  non-concluded assets may remain open.
- `--require-no-unmatched` -- pass when `len(unmatched) == 0`: no traffic host is
  missing from the inventory.

Equality passes for every comparison. `--json` still prints the underlying report.
There is no default gate: a threshold is required, and one supplied without `--gate`
is rejected rather than silently ignored.

Exit codes:

- `0` -- gate PASS: every declared threshold held.
- `1` -- gate FAIL: at least one declared threshold was missed.
- `2` -- parameter error: `--gate` with no threshold, a threshold given without
  `--gate`, or a threshold out of range/negative. Nothing is written to stdout; the
  reason goes to stderr.

Output names each check: a `coverage gate: PASS` or `coverage gate: FAIL` first line,
then one `  [PASS|FAIL] <name>: required <threshold>, actual <value> -- <why>` line per
threshold (the name is dashed, e.g. `min-evidenced-ratio`), then the concrete misses --
`uncovered assets (N):` listing `  <coverage> <host>  (<reason>)`, and/or
`unmatched traffic hosts (N):` listing `  <host>  flows=<n>` -- and a trailing
`assets=... concluded=... untouched=... ratio=... evidenced_ratio=...` summary line.

At the library level `coverage.gate()` fails closed: called with no threshold it
returns `passed=False` with no checks. The CLI rejects that call as a parameter error
first, so an ungated run can never be mistaken for a pass.

## Convergence Playbook

Coverage is a goal the operator sets, not one the tool infers, so there is no default
threshold: "covered enough to close or switch phase" depends on the engagement's
scope, authorization, and appetite for open leads. Decide it, run it, and keep the
output with the handoff.

A workable order:

1. Clear never-touched assets first: `--gate --max-untouched 0`. Every failure names
   an asset no traffic reached -- pure, unambiguous work.
2. Once nothing is untouched, raise the evidence bar:
   `--gate --max-untouched 0 --min-evidenced-ratio 0.8`. Pick the fraction you can
   defend: a broad host inventory rarely reaches a high value, while a small
   lead-driven engagement can aim higher. Each failure is a `touched`-but-not-concluded
   host; drive its lead to a terminal state or record why it stays open.
3. Bound the open work: `--max-unresolved-leads N` freezes how many leads may remain
   at close, and `--require-no-unmatched` forces every exercised host into the
   inventory.

An accepted gap never stands in for coverage -- `accepted_gaps` is a decision to stop,
so it raises no ratio, and using it to pass a gate is exactly the inflation this report
refuses to count.
