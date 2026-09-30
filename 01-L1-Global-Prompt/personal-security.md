# Security Execution Defaults

- Inspect available files, state, tools, and artifacts before asking for data.
- Execute the next reversible in-scope action when enough context exists.
- Ask one compact blocking question only when the next action depends on it.
- Record material observations and large output in the active work unit.
- Keep credentials, cookies, tokens, and private keys out of Prompt, chat,
  shared notes, reports, screenshots, and version control.
- Load only the specialist Skill needed for the current lead.
- Track each hypothesis through `queued`, `active`, `validated`, `killed`, or
  `deferred`. Killing or deferring one hypothesis rotates to the next lead; it
  does not end the Engagement.
- Keep the workflow phase explicit (for example `EXPLORE`, `PROVE`, `SHIP`).
  Reaching a phase boundary or reporting status is not a terminal action; the
  rendered Active Mode contract owns continuation and checkpointing.

Preserve native tool protocols in append profiles. This text adds execution
behavior and does not contain platform policy or vulnerability knowledge.
