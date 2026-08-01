---
name: browser-js-orchestrator
description: Orchestrate browser JavaScript analysis and runtime reverse engineering for remote pages, local bundles, extensions, request signing or encryption, obfuscated code, behavior modification, and reusable client-side tooling. Use at Browser-JS task start, resume, lead selection, reconstruction, validation, or deliverable selection without assuming a CTF, vulnerability, browser extension, or user script.
---

# Browser JavaScript Orchestrator

Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`.
Infer the requested outcome from the task and existing state. Ask only when a
missing acceptance criterion changes the implementation materially.

## Observe And Select

1. Preserve supplied files and capture a normal page baseline: navigation,
   network, console, storage, workers, loaded scripts, source maps, and request
   initiators relevant to the requested behavior.
2. Rank concrete call-chain leads above broad bundle deobfuscation. Start from
   an observed request, event, DOM mutation, worker message, storage change, or
   exported function and trace inward.
3. Prefer a narrow runtime hook that records inputs, outputs, receiver, stack,
   and timing. Use breakpoints when a hook or source map cannot distinguish the
   leading hypotheses.

## Reconstruct And Verify

1. Check source maps and readable modules before deobfuscation. Run `webcrack`
   only on selected minified, obfuscated, Webpack, or Browserify inputs.
2. Reproduce the smallest required dependency set. Do not build a large browser
   environment shim before runtime evidence identifies the missing inputs.
3. Keep `observed`, `inferred`, and `verified` conclusions distinct. Validate a
   reconstruction with captured vectors, a clean-page replay, or a controlled
   differential test.
4. Load `ctf-web`, `api-security`, or `reverse-orchestrator` only when the active
   lead enters that specialist domain.

## Deliver

Choose the artifact from the requested outcome. It may be recovered source,
call-flow or protocol documentation, a Node module, request reproducer, runtime
probe or hook, patched bundle, browser extension, user script, or another
directly usable form. Preserve analysis evidence under `artifacts/`, reusable
code under `scripts/`, and final outputs under `deliverables/`. Checkpoint the
exact next action after material progress.
