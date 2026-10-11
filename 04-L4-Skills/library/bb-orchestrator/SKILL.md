---
name: bb-orchestrator
description: Use when coordinating an authorized Bug Bounty or VDP Engagement across recon, lead selection, specialist testing, evidence, and reporting.
---

# Bug Bounty Orchestrator

The written program rules own scope, identity, rates, and side-effect limits.
Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`
before choosing work.

## Resume And Scope Gate

1. Resume the recorded next action when its asset is still in scope and its
   hypothesis remains useful.
2. Treat hosts, applications, buckets, APIs, and organizations discovered from
   DNS, JavaScript, certificates, redirects, or search as `candidate` assets.
   Record provenance, but do not actively request them until a written rule or
   user instruction matches them.
3. A shared registrable domain, brand, certificate, CDN, or code reference is
   evidence of relationship, not authorization. Moving a candidate into scope
   requires a Scope revision and source in `notes/SCOPE.md`.
4. Out-of-scope candidates never block work on remaining in-scope leads.

## Coverage Drives Convergence

Before choosing the next lead, read the coverage rollup (`bb-stack coverage <SLUG>`)
rather than opening a blind probe; run `bb-stack guide` for the related graph and
inventory commands. Push the assets that move a gate: `untouched` (never touched) and
`unresolved` entries (a lead exists but never closed). Add `unmatched` hosts -- traffic
you exercised but the inventory never listed -- to the asset inventory; they are
discoveries, not noise. `accepted_gaps` is a recorded decision to stop, not coverage
evidence. Never declare coverage complete before running the gate: to close or change
phase, state thresholds explicitly with `bb-stack coverage <SLUG> --gate ...` and get PASS.

## Rank A Small Queue

Use `bb-recon` for initial and resumed reconnaissance. Read its coverage and
signals before ranking leads. Adaptive recon may run beside later testing, but
unfinished baseline stages remain visible until completed or blocked.

Keep at most five active leads. Rank them softly by:

```text
concrete signal + trust-boundary reach + business impact + reproducibility
- time cost - side effects
```

Prefer leads with an observed server-side boundary: undocumented business APIs,
client-visible authorization or signing logic, object or tenant identifiers,
read/write/upload/export operations, alternate API versions, and state-changing
workflows. Login friction, generic headers, template secrets, OCR, broad CVE
searches, and version banners stay lower unless evidence connects them to an
actual boundary.

The ranking is guidance, not a fixed attack order. Preserve one anomaly or
model-generated lead when it has a concrete differentiating request. A model
may choose another lead when it records the stronger signal or cheaper proof.
Load only the specialist Skill for the selected lead.

Use `bb-methodology` only when the queue is empty, stale, or lacks diversity;
use `bug-bounty` only as a broad reference. Their time-box or stop language can
rotate a lead but cannot end the engagement.

## Prove Without Overclaiming

Every conclusion has one proof level:

- `signal`: code, schema, metadata, or behavior suggests a hypothesis.
- `primitive`: a controlled request reproduces a capability.
- `impact`: a negative control or distinct authorized identity/object proves a
  security boundary was crossed.
- `confirmed`: primitive, impact, prerequisites, cleanup, and reproducible
  evidence are complete.

For each test, record the baseline, one changed variable, identity context,
response delta, proof level, claim basis (`observed` or `inferred`), evidence
path, cleanup, and next action. An owned upload/download round trip proves that
round trip only; it does not prove cross-user access. A response schema or empty
sensitive field is not actual sensitive-data disclosure. Observations from
different products or backends form a chain only after a shared identity,
secret, object, or request path is demonstrated.

Cluster effects under the narrowest demonstrated root cause. Client-visible
signing material is reportable as an authorization flaw only when the server
accepts it as an authorization boundary; read, write, upload, and business
operations reached through that boundary are impact evidence, not automatic
separate findings.

Before ranking or opening a lead, read what was already captured: list the hosts
in the engagement traffic store, search the captured flows for the endpoint,
header, and parameter in question, and diff the identities you already replayed.
A hidden parameter, an ignored endpoint, or a cross-identity delta found there
costs no new traffic. Open a fresh probe only when the capture lacks the request,
or when the probe proves what the capture cannot.

## Delegate Execution

`04-L4-Skills/agents.yaml` declares which role may be handed a lead; run
`bb-stack guide` to find the roster command, then plan a batch with
`bb-stack agents plan --file <requests.json>`; that command refuses a batch whose
slices would write into one another, so run it before spawning rather than
discovering a collision later.

Delegate when a unit is independent and self-contained: recon for an unmapped
target, one concrete request to prove or refute, one artifact to reverse. Keep
the lead when the next step depends on what you just learned, or when the work
is a single request you can issue yourself.

Each delegated unit gets its own role, its own output directory, and exactly:

1. The role and the one unit of work, stated so it needs no context from you.
2. The in-scope target and the authorization basis you already recorded.
3. The write set the plan assigned, and nothing outside it.
4. The acceptance condition: what a passing result looks like.
5. The return contract: write `result.json` with `conclusion`, `claim_basis`
   (`observed` or `inferred`), `evidence_paths`, and `blocked_by`.

Workers return a conclusion and the path to it, not their transcript. Read the
conclusion, open evidence files only when the conclusion is load-bearing for the
next decision, and never pull a worker's raw execution log into your own context.

A delegated worker does not delegate again. When a unit turns out to need two
different specialisms, finish it, then plan a separate batch for the second.

Synthesize from the returned conclusions: state what was proven, what was
refuted, and what remains open. A worker reporting success does not raise proof
level on its own; the claim still needs the observation that supports it.

## Checkpoint And Continue

Use `hypotheses.md` for leads and `notes/findings-live.md` for findings. Store
large evidence under `artifacts/` or `recon/`. Keep complete credentials and
tokens only in ignored local secret storage; use a stable label and redacted
form in chat, STATUS, HANDOFF, and normal notes.

After material progress, update the active lead/finding, `STATUS.md`,
`SESSION-HANDOFF.md`, then `engagement.yaml`. In continuous mode immediately
execute the next useful in-scope action. Use `triage-validation` and
`report-writing` during SHIP, or earlier when the user requests delivery.
