---
name: ctf-orchestrator
description: Orchestrate CTF challenge triage, routing, solving, verification, and writeup. Use when a challenge, remote competition service, source bundle, or local security puzzle is supplied, especially when deciding which specialist Skill to load or resuming saved solve state.
---

# CTF Orchestrator

Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`
when present. Keep quick challenges lightweight.

1. Inventory the statement, files, service, success condition, and existing work.
2. Classify the dominant path and load one specialist Skill. For HTTP apps,
   APIs, browser flows, and template engines, load `ctf-web`.
3. Capture a normal baseline before fuzzing and preserve material responses.
4. Build the smallest reproducible primitive, then chain only as required for
   the flag or stated success condition.
5. Save reusable exploit code under `scripts/` and evidence under `artifacts/`.
6. Verify the exact flag or success condition. Load `ctf-writeup` after solving.

If a lead fails, record why and rotate category or surface. Do not import Bug
Bounty severity, identity headers, or submission gates into a standalone CTF.
