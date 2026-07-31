---
name: bb-orchestrator
description: Orchestrate an authorized Bug Bounty or VDP engagement from existing scope and L3 state. Use at engagement start, resume, target switch, when selecting the next lead, or when coordinating specialist security skills without ending the overall engagement.
---

# Bug Bounty Orchestrator

Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`.
The written program rules own scope, identity, rate, and side-effect limits.

1. Resume the exact recorded next action when it remains valid.
2. Otherwise inventory current evidence and rank a small queue of concrete leads.
3. Load one specialist Skill for the active lead. Specialist stop or pivot rules
   close that lead, not the engagement.
4. Establish a baseline, change one relevant input or identity context, compare
   the delta, and save reproducible evidence.
5. Update hypothesis/finding notes, STATUS, HANDOFF, then `engagement.yaml`.
6. Continue in continuous mode while a useful in-scope action remains.

Use `bb-methodology` for hunting heuristics and `bug-bounty` as a broad
reference. Use `triage-validation` and `report-writing` only in SHIP or when the
user requests a report. Do not copy credentials or complete tokens into notes,
Prompt, reports, or shared artifacts.
