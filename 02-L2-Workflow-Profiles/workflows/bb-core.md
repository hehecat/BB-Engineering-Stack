# Bug Bounty Workflow

The written program scope owns assets, exclusions, rates, identity rules, and
side-effect limits. Resume from `engagement.yaml`, `notes/SCOPE.md`,
`SESSION-HANDOFF.md`, and `STATUS.md` before selecting a new lead.

At engagement start, resume, or target switch, route first through
`bb-orchestrator`. Use `bb-methodology` to rank the hunting path, then load only
the specialist Skill matching the active lead. Platform overlays supply program
rules and are not Skills.

- `EXPLORE`: map and rank in-scope surface.
- `PROVE`: reproduce or kill one lead and preserve evidence.
- `SHIP`: validate, redact, and package only on request.

For material progress record surface, changed input, identity context, baseline
versus test delta, primitive or impact, evidence path under `artifacts/`, and
exact next action.
Specialist Skills may rotate a lead but do not terminate the engagement.
