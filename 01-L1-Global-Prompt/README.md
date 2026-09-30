# L1 Global Prompt

L1 contains short platform-neutral execution behavior. It does not contain
target scope, vulnerability payloads, platform submission rules, usernames,
tool paths, or machine configuration.

Every render includes `personal-security.md` and
`languages/<BB_AGENT_LANGUAGE>.md`, resolved from the configured agent language.
`replacement-runtime.md` supplies only the minimum runtime contract needed when a
profile sets `prompt_mode: replacement`. Such a profile renders all of these
fragments into a standalone system Prompt; append profiles add them to Claude
Code's native system Prompt instead.
