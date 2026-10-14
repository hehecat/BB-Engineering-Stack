# Web And API Assessment Domain

Route through `security-orchestrator`, then choose the smallest matching Web or
API specialist such as `api-security`, `auth-hacking`, `idor`, or
`dast-automation`. Capture a normal HTTP baseline and preserve material
requests and responses under `artifacts/http/`; use a browser only when client
state or JavaScript execution matters.

For every discovered web asset, fetch its production JavaScript and any `.map`,
then extract endpoints, client-visible credentials, signing rules, and
environment identifiers. Record the extracted surface in
`notes/asset-inventory.md`, any client-visible secret or trust assumption in
`notes/findings-live.md`, and add the extracted endpoints to the tested
surface. A bundle shipped with a credential is a finding before it is
exercised.

Client-side analysis can hand off to `browser-js-orchestrator` without changing
the assessment Scope or delivery rules. Keep automated discovery within the
written rate and action conditions.
