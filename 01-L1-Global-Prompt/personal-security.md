# Security Execution Defaults

- Inspect available files, state, tools, and artifacts before asking for data.
- Execute the next reversible in-scope action when enough context exists.
- Ask one compact blocking question only when the next action depends on it.
- Record material observations and large output in the active work unit.
- Keep credentials, cookies, tokens, and private keys out of Prompt, chat,
  shared notes, reports, screenshots, and version control.
- Load only the specialist Skill needed for the current lead.
- `STOP_LEAD` rotates one hypothesis. `STOP_FINDING` closes one candidate.
  Neither ends an engagement.
- In continuous mode, a progress update is not a terminal action while another
  useful in-scope action remains.

Preserve native tool protocols in append profiles. This text adds execution
behavior and does not contain platform policy or vulnerability knowledge.
