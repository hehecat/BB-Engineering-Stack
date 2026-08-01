# Browser JavaScript Domain

Start with `browser-js-orchestrator`.
Analyze browser JavaScript from observable behavior toward the smallest
relevant call chain. Establish the page, network, console, storage, workers,
loaded scripts, source maps, and request initiators before broad static work.
Prefer a narrow runtime hook around the observed boundary; use breakpoints only
when hooks and source maps cannot distinguish the hypotheses.

Use Chrome DevTools MCP when the strict Profile is active. In a normal workspace
session, run the returned `browser_start` command once, then use
the managed `chrome-devtools` CLI; `bb-stack browser stop` cleans up the isolated
runtime. Strict Browser-JS launch starts the same CDP runtime automatically.
Fall back to Playwright for page interaction. Use `webcrack` only on selected minified,
obfuscated, Webpack, or Browserify inputs, not indiscriminately on every bundle.

Reproduce only the dependencies required by the target function. Validate the
result against a captured baseline or differential replay. Choose the output
from the requested outcome: recovered source, call-flow notes, protocol/API
documentation, a Node module, a runtime probe or hook, a patched bundle, a
browser extension, a user script, or another directly usable artifact.
