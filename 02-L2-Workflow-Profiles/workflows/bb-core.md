# Bug Bounty Workflow

The written program scope owns assets, exclusions, rates, identity rules, and
side-effect limits. Resume from `engagement.yaml`, `notes/SCOPE.md`,
`SESSION-HANDOFF.md`, and `STATUS.md` before selecting a new lead.

Before active target traffic, require `lifecycle: active` and
`authorization.status: verified` in `engagement.yaml`, with the written source
recorded in `notes/SCOPE.md`. If authorization is pending, user-asserted, or
revoked, stop active testing, preserve state, and complete the authorization
repair first. Never infer verification from asset ownership or target access.

At engagement start, resume, or target switch, route first through
`bb-orchestrator`, then load only the specialist Skill matching the active lead.
Use `bb-methodology` only when the current queue needs new hunting ideas.
Platform overlays supply program rules and are not Skills.

Only assets matched by the current written Scope are active targets. Record an
adjacent asset discovered from DNS, JavaScript, certificates, redirects, or
search under `Candidate Assets`; relationship alone does not add it to scope.
Promoting a candidate requires a Scope revision with its authorization source.

Unless the written program or `notes/SCOPE.md` sets another value, production
BB/VDP work uses these per-lead ceilings:

- one minimal reversible state-changing action;
- one inert upload no larger than 1 KiB, using only the extension needed for the
  hypothesis;
- three adjacent object identifiers after the owned/control baseline;
- five credential guesses on one authentication surface;
- ten OTP validation requests on a controlled identifier, without additional
  message sends.

Stop when the smallest proof is captured, record cleanup, and request an
explicit Scope/budget revision before exceeding a ceiling. These defaults do
not apply to standalone CTF or local lab workflows.

- `EXPLORE`: map and rank in-scope surface.
- `PROVE`: reproduce or kill one lead and preserve evidence.
- `SHIP`: validate, redact, and package only on request.

For material progress record surface, changed input, identity context, baseline
versus test delta, proof level, observed versus inferred claim basis,
root-cause cluster, evidence path under `artifacts/`, cleanup, and exact next
action. Use `notes/findings-live.md`; do not invent a parallel findings log.
Put complete discovered secrets only in ignored local secret storage with mode
600. Chat, STATUS, HANDOFF, and normal notes use a stable label plus a redacted
form.
Specialist Skills may rotate a lead but do not terminate the engagement.
