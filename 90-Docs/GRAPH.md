# Engagement Knowledge Graph

One derived index over the artifacts an Engagement already keeps, so the
orchestration layer can ask "what do we have and what touches what" without
reading every markdown file into context.

## Why It Exists

- A directory listing and a pile of markdown do not show the *whole* picture:
  which hosts matter, which endpoints a finding crossed, how many leads are
  still open, and where a coverage gap sits. You only see it by reading
  everything.
- Reading everything is exactly what burns context. The graph is the cheap
  first look: read a summary, then pull only the node or neighborhood you need.
- It is context economy, not new knowledge. Anything the graph says is already
  on disk; the graph is a projection of it.

## Derived, Not Authoritative

- The graph is a *derived index*. Authority stays with the source artifacts:
  `notes/asset-inventory.md`, `recon/state.json`, `hypotheses.md`,
  `notes/findings-live.md`, and the captured traffic in `traffic/flows.db`.
- `graph build` reads those and **rewrites the graph from scratch**, so there is
  one direction of truth and no write-drift to reconcile. Editing the graph
  directly is never the move -- edit the source, rebuild.
- Deleting `<engagement>/graph/` costs nothing but a rebuild. If a query and the
  source disagree, the source wins.
- Location and permissions: `<engagement>/graph/nodes.db`, file `0600` inside a
  `0700` `graph/` directory, ignored by the Engagement `.gitignore`.

## When To Build

- [ ] Build after the sources move: a recon run, new asset rows, new findings or
      hypotheses, or fresh traffic. A stale graph answers with the old shape.
- [ ] Build before a query session. Read commands never auto-build: an absent or
      empty graph would silently answer "nothing imported", so `summary`,
      `search`, `node`, `neighbors`, and `stats` refuse and point at
      `graph build` instead.
- [ ] Build narrowly with `--source asset-inventory|recon|hypotheses|findings|traffic`
      (repeatable) when you only need one slice; omit it to import every source.

```bash
bb-stack graph build <SLUG>
bb-stack graph build <SLUG> --source traffic --source findings
```

## Query Path

Cheap to expensive: read the summary first, search to narrow, then pull one node
or its neighborhood.

- [ ] `bb-stack graph summary <SLUG> [--top N]` -- counts by node kind and edge
      kind plus the heaviest nodes per kind. Start here; it never returns node
      content.
- [ ] `bb-stack graph search <SLUG> [--kind KIND] [--label TEXT] [--key KEY] [--limit N]`
      -- the light listing: identity and source only (`id`, `kind`, `key`,
      `label`, `source`, timestamps). Use it to find the `id` you want.
- [ ] `bb-stack graph node <SLUG> KIND KEY` -- one node in full, with its
      incident edges and attributes.
- [ ] `bb-stack graph neighbors <SLUG> NODE_ID [--depth D] [--direction both|out|in] [--kind KIND]`
      -- expand around a node id. Bounded (`--depth` caps at 5; the walk stops
      at a node budget and reports truncation).
- [ ] `bb-stack graph stats <SLUG>` -- store-level counters and the build time.
- [ ] Every command takes `--json` for machine consumption; the default is human
      text.

## Node And Edge Kinds

Nodes: `asset`, `service`, `endpoint` describe real surface; `finding`, `lead`,
`evidence`, `recon-branch`, `coverage-gap` describe the reasoning about it.

Edges: `exposes` walks a host down to its services and endpoints; `targets`
links a recon branch to the asset it was opened against; `evidenced-by` and
`leads-to` tie reasoning nodes to the surface they touch.

The Python API mirrors the CLI: `bb_stack.graph.graph_for(paths, slug)` opens the
store, `build(paths, slug, source=...)` rebuilds it, and `summary` / `search` /
`node` / `neighbors` / `stats` query it.
