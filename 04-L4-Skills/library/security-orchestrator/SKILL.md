---
name: security-orchestrator
description: Orchestrate an authorized security assessment across Web/API, Android, iOS, network, cloud, LLM/agent, source, supply-chain, IaC, and container domains. Use at assessment start, resume, scope validation, lead selection, cross-domain handoff, evidence grading, or checkpointing without importing Bug Bounty, CTF, or standalone-analysis policy.
---

# Security Assessment Orchestrator

Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`.
The written Scope owns assets, identities, rates, side effects, credentials, and
exclusions.

## Select The Domain

1. Resume the exact recorded action when it remains relevant and in scope.
2. Classify the active lead by the boundary being tested, not only by artifact
   type: Web/API, Android, iOS, network/identity, cloud, LLM/agent, or source and
   supply chain.
3. Load one domain specialist first. Add another only when observed evidence
   crosses that boundary inside the same written Scope.
4. Keep workflow and platform policy stable during a specialist handoff.

## Prove And Record

Capture a control, one changed variable, identity or privilege context,
observed delta, evidence path, cleanup, and next action. Separate a signal from
a reproduced capability and from demonstrated impact. Do not infer access from
schemas, policy text, scanner labels, or client-side code without checking the
effective boundary.

Keep large raw output under `artifacts/`, reusable commands under `scripts/`,
and current findings in `notes/findings-live.md`. Store complete credentials or
tokens only in ignored local secret storage and refer to them by stable labels.

After material progress update `STATUS.md`, `SESSION-HANDOFF.md`, and
`engagement.yaml`. In continuous mode proceed to the next useful scoped action;
in interactive mode finish the requested bounded task and preserve the exact
next action.
