# Security Analysis Workflow

Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and `STATUS.md`
before analysis. Treat the supplied artifact, URL, code, bundle, extension, or
fixture as the work-unit boundary. This workflow is for behavior analysis and engineering;
do not import Bug Bounty severity, submission, production action-budget, or
adjacent-asset rules unless the task is explicitly routed to Bug Bounty.

Record observations and static conclusions separately in
`notes/analysis-log.md`. Save raw evidence under `artifacts/`, reusable code
under `scripts/`, and only requested final outputs under `deliverables/`.

Start with the orchestrator selected by the active Profile. Load a security or
reverse-engineering specialist only when the observed lead enters that domain.
