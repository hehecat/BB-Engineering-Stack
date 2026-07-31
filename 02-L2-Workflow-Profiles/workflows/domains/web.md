# CTF Web Domain

For HTTP applications, APIs, browser clients, identity flows, template engines,
and smart-contract Web frontends/backends, route first through
`ctf-orchestrator`, then load `ctf-web` as the specialist Skill. Use
`security-arsenal` only for payload detail after the active bug class is known.

Capture a normal HTTP baseline, preserve material requests and responses under
`artifacts/http/`, and keep reusable solve or exploit code under `scripts/`.
Use the browser only when client state or JavaScript execution matters.
