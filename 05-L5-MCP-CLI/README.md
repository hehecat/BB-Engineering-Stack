# L5 MCP And CLI

`capabilities.yaml` maps stable capabilities to interchangeable providers.
Profiles declare required and optional capabilities. The launcher registers
only usable MCP servers and leaves high-context optional MCPs out unless
explicitly requested.

The `workspace` profile renders the project `.mcp.json` used by plain
`claude`. It intentionally contains no domain MCP, so network, cloud, source,
mobile, and CTF sessions do not inherit browser tool schemas. Normal sessions
remain CLI-first; profile-specific MCPs stay in strict launches.

The `browser-js` profile uses Chrome DevTools MCP for runtime network, console,
source-map, page, and script observations and uses `webcrack` as a CLI for
selected static inputs. Plain workspace sessions can call the companion
`chrome-devtools` CLI after `bb-stack browser start` without hot-loading another
MCP. The strict Browser-JS
profile does not also load Playwright, avoiding duplicate browser tool schemas.

```bash
bb-stack doctor --profile ctf-web --strict --probe-mcp
bb-stack mcp render --profile ctf-web \
  --output /tmp/mcp.json --artifact-root /tmp/browser-artifacts
bb-stack mcp probe /tmp/mcp.json
bb-stack doctor --profile browser-js --strict --probe-mcp
```

Doctor distinguishes command/path presence, required local configuration,
capability readiness, and direct MCP handshake. Playwright uses system Chromium
in headless/no-sandbox mode, so no desktop session is required.
