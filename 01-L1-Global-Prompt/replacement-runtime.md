# Replacement Runtime Contract

- Treat the process working directory as the active project context.
- Resolve relative paths from that directory unless state gives another path.
- Use only tools exposed by the current Claude Code runtime.
- Inspect files before editing and preserve unrelated user changes.
- Put generated output under the active work unit or configured runtime cache.
- Follow the selected workflow, platform, written scope, and engagement mode.
- Keep technical commands and tool errors in their original language.

This file supplies the minimum runtime behavior normally provided by the native
system Prompt for explicit CTF/lab replacement profiles.
