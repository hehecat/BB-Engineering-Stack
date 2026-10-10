# Traffic Library

The Engagement traffic store. The recorder and the managed browser write every
request/response pair into one SQLite file per Engagement, and the agent reads
it back through search instead of re-sending requests.

## Why It Exists

- Recon keeps tool output; this keeps the wire. One tool call shows one
  response, so hidden parameters, ignored endpoints, repeated object ids, and
  cross-identity deltas stay invisible until you look across everything that was
  already sent.
- Search the capture before sending anything new: no extra traffic, no extra
  side effects, no rate-limit budget spent.
- Use it as the Engagement's own proxy history and revisit it the way a human
  pentester scrolls back through Burp, rather than reading only the last
  command's stdout.

## Location And Permissions

- One store per Engagement:
  `$BB_WORK_ROOT/engagements/<SLUG>/traffic/flows.db`.
- The file is mode `0600` inside a `0700` `traffic/` directory.
- `traffic/` is ignored by the Engagement `.gitignore`. Keep it that way.

Security boundary. Treat the store as live credentials, not as notes:

- It contains `Cookie`, `Authorization`, bearer tokens, session ids, CSRF
  values, and anything a backend echoed back.
- Never copy, upload, attach, paste, or summarize raw flows outside the
  Engagement. Redact to a stable label (`<SESSION-A>`) in chat, notes, and
  reports.
- Never commit it, and never bundle it into a report, screenshot, or archive.
- Pull the slice you need; do not dump a whole session into context.

## Record Traffic

Start the recording proxy. It writes flows straight into the store -- there is
no stdout capture and no separate import step.

```bash
"$BB_STACK_ROOT/00-L0-Runtime/bin/bb-traffic" --engagement SLUG
```

- [ ] Create the Engagement first. The slug resolves through the stack
      (`StackPaths.engagement`), so pass the slug and let the launcher build the
      path; do not hand-write a store path.
- [ ] Have `mitmdump` available. The launcher prefers
      `$BB_STACK_ROOT/.runtime/bin/mitmdump`, then `PATH`; install it on demand
      with `bb-stack tool install mitmproxy` when it is missing.
- [ ] Point the client at the proxy: `HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:8080`,
      or Chromium `--proxy-server=http://127.0.0.1:8080`. The proxy listens on
      mitmdump's default port unless you pass `-p PORT`.
- [ ] Set `--engagement` or `$BB_ENGAGEMENT`; with neither the launcher demands
      the slug and exits instead of recording nothing.
- [ ] Make the client trust the CA before expecting HTTPS bodies. Import
      `$HOME/.mitmproxy/mitmproxy-ca-cert.pem`, or set `SSL_CERT_FILE` /
      `REQUESTS_CA_BUNDLE` to it for CLI HTTP tools. Without that trust step the
      TLS handshake fails and the flow lands with `response_status = NULL`.
- [ ] Overwrite the location with `--db <path>` when needed. The launcher also
      exports `BB_TRAFFIC_DB` (absolute store path) and `BB_ENGAGEMENT` (slug) to
      the proxy process.
- [ ] Confirm the capture after the first request: `list_traffic_hosts` should
      list the host. The store file appears on the first recorded flow, so a
      missing file means "nothing captured yet", not a failure. A store write
      error is logged and never breaks the proxy, so verify rather than assume.
- [ ] Arguments `bb-traffic` does not recognise pass through to `mitmdump`
      verbatim (`bb-traffic --engagement SLUG -p 8899`); `--` ends `bb-traffic`'s
      own flags explicitly.

`bb-traffic` is a launcher inside the runtime tree and is not yet installed as a
`PATH` wrapper, so call it by its in-tree path as shown above.

## Read It Back

Read from cheapest to most specific:

1. `list_traffic_hosts()` -- start here. One rollup row per host (flow count,
   distinct paths, pending responses, first/last seen) so you see the shape of
   the capture before pulling a flow. Takes no arguments.
2. `search_traffic(host, path_contains, method, status, client, text, since,
   until, limit)` -- narrow the capture. Returns summaries with the full URL and
   id, never bodies. `limit` defaults to 20 and caps at 200.
3. `read_flow(id, max_bytes, raw)` -- pull one flow in full: request and response
   headers, bodies, status, timing. `max_bytes` defaults to 16384; a capped body
   is flagged `body_truncated` and reports `body_bytes`/`bytes`. Set `raw=true`
   for base64 bytes instead of decoded text.
4. `diff_flows(first, second)` -- the IDOR / broken-authorization query. Compares
   two flows field by field (method, URL, status, every request and response
   header, response body) and reports exactly what changed. Send the same request
   as two identities, or replay it once, then diff: a changed cookie,
   `Authorization` header, or body is the delta.
5. `traffic_stats()` -- capture-wide counters (flows, hosts, pending, by client,
   by status). Use it to confirm a capture is populated and to spot identities
   and statuses before filtering.

Availability: capability `traffic.history` (MCP server `traffic`), optional in
the `web`, `browser-js`, and `assessment-web` profiles. The server resolves the
store from `BB_TRAFFIC_DB`, otherwise from the `BB_ENGAGEMENT` slug; with neither
set it reports a configuration error, and a set-but-absent file simply answers
empty.

CLI-first sessions without the traffic MCP reach the same store:

```bash
bb-stack traffic hosts SLUG --json
bb-stack traffic search SLUG --host HOST --text TOKEN --status 200 --json
bb-stack traffic read SLUG ID [--max-bytes N] [--raw] --json
bb-stack traffic diff SLUG FIRST SECOND --json
bb-stack traffic stats SLUG --json
```

## Search Semantics

- `text` matches host, path, query, request and response headers, and request
  and response bodies. A token that only ever appears in a header is findable.
- Whitespace-separated terms must all appear (`alice bob` means both).
  Punctuation is literal, so `X-Internal-Debug` is a string and not an FTS5
  operator.
- Matching is per whole token: `lengthyzztok` does not find `lengthyzztokzz`.
- Only decoded text is indexed. Binary media (`image/*`, `video/*`, `audio/*`,
  `font/*`, `application/octet-stream`) is never indexed, and only the first
  256 KiB of a body enters the index. The captured bytes stay in the store and
  are reachable with `read_flow(raw=true)`.
- Capture is bounded as well: the recorder stores at most 2 MiB per direction
  (`MAX_BODY_BYTES`) and marks the flow's `source` with `truncated=request` /
  `truncated=response`, so a partial stored body is never mistaken for a whole
  one.
- Listings are newest first. A blank `text` filters nothing, and `since`/`until`
  compare ISO8601 `started_at` bounds.

## Operating Checklist

- [ ] Before a new probe, search the capture for the endpoint and the parameter
      you are about to send.
- [ ] Before ranking a lead, check whether the flow already exists; a found
      request needs no new traffic.
- [ ] For any identity question, `diff_flows` the two identities instead of
      inferring from a single response.
- [ ] Before writing notes or reports, redact credentials to a stable label.
- [ ] Before delivering, confirm `traffic/` stays ignored and out of every
      archive.
