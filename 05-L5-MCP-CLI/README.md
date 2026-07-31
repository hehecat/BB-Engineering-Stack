# L5 MCP And CLI

`capabilities.yaml` maps stable capabilities to interchangeable providers.
Profiles declare required and optional capabilities. The launcher registers
only usable MCP servers and leaves high-context optional MCPs out unless
explicitly requested.

The `workspace` profile renders the project `.mcp.json` used by plain
`claude`. It contains the small common Headless baseline, currently Playwright
when available. Android and Reverse execution remains CLI-first; optional
high-context MCPs stay in explicit Profile launches.

```bash
bb-stack doctor --profile ctf-web --strict --probe-mcp
bb-stack mcp render --profile ctf-web \
  --output /tmp/mcp.json --artifact-root /tmp/browser-artifacts
bb-stack mcp probe /tmp/mcp.json
```

Doctor distinguishes command/path presence, required local configuration,
capability readiness, and direct MCP handshake. Playwright uses system Chromium
in headless/no-sandbox mode, so no desktop session is required.
