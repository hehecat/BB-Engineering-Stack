# LLM And Agent Security Domain

Route through `security-orchestrator`, then use `llm-security` for direct or
indirect prompt injection, RAG and memory boundaries, MCP and Skill trust,
agent tool use, multimodal input, system context exposure, and excessive
agency. Use `api-security` separately when the lead is a conventional API
authorization or quota issue.

Record model and application version, system features, tools, identities,
memory scope, corpus state, exact conversation sequence, and control run. Save
transcripts and structured results under `artifacts/llm/`; use unique canaries
and separate model noncompliance from an application security boundary crossed
through data, identity, persistence, or tool execution.
