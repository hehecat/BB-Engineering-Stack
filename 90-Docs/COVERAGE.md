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
