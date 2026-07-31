# Keysmith Integration

`bb-claude` is the default because it selects Prompt and MCP per Engagement.
Keysmith is available when raw `claude` should receive one persistent global
replacement profile.

```bash
bb-stack keysmith fetch
bb-stack keysmith install --profile ctf-replacement --yes
source "$HOME/.zshrc"
bb-stack keysmith status
```

The adapter fetches the pinned commit from `stack.yaml`, lets Keysmith manage
backups/import blocks/wrapper ownership, then writes the stack-rendered Prompt.
The small imported memory file is only a pointer, preventing duplicate workflow
text.

```bash
bb-stack keysmith uninstall --yes
source "$HOME/.zshrc"
```

Installation changes every raw `claude` shell invocation. `bb-claude` resolves
the real CLI executable and remains deterministic even when the shell wrapper is
active. Prompt injection changes instruction delivery; model/provider behavior
still has to be measured with the included smoke tests.
