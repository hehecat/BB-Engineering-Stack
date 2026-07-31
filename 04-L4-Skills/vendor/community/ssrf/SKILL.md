---
name: ssrf
description: Advanced SSRF testing methodology for bug bounty and application security work. Use when testing or reviewing server-side request forgery, URL preview APIs, import/export APIs, webhooks, callbacks, file converters, image fetchers, analytics reports, OAuth controllers, cloud metadata access, internal service reachability, DNS rebinding assumptions, redirect bypasses, blind SSRF, SSRF-to-file-read, and SSRF chains to credentials, internal APIs, or RCE.
---

# SSRF Testing

## Core Posture

Treat SSRF as backend reachability controlled by user input. Identify the fetcher, network position, URL parser, redirect policy, response channel, and internal trust available to the backend.

## Priority Patterns

- Preview/export/import APIs, webhook callbacks, image/avatar fetchers, PDF/renderers, and game/report exports.
- Cloud metadata, internal admin panels, localhost services, service discovery, and private IP ranges.
- Blind SSRF through timing, DNS, collaborator callbacks, error messages, titles, content length, and status changes.
- Allowlist bypass through redirects, parser mismatch, DNS rebinding, IPv6, decimal/octal IPs, and scheme confusion.
- SSRF chains to credentials, file read, internal APIs, command execution, or cloud account access.

## Assessment Loop

1. Find URL-like inputs in query, JSON, GraphQL, multipart, metadata, webhooks, imports, and callbacks.
2. Determine fetch behavior: schemes, redirects, DNS resolution, headers, method, body, timeout, and response exposure.
3. Start with attacker-observed URL callbacks and controlled redirects.
4. Test allowlist and internal-target bypasses carefully.
5. Confirm backend reachability and impact through data, credentials, internal action, or side channel.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| URL fetch | Does backend request attacker-controlled URL? |
| Redirect | Are allowlists checked before or after redirects? |
| Metadata | Can cloud credentials or metadata be reached? |
| Blind response | Is title, timing, status, or size observable? |
| Localhost | Can internal admin/control APIs be reached? |

## Variant Playbook

- Test schemes, redirects, DNS rebinding, IPv6, localhost aliases, encoded hosts, userinfo, and mixed parsers.
- Place URLs in nested JSON, GraphQL variables, file metadata, webhook targets, and import fields.
- Compare direct fetchers, renderers, background jobs, and async processors.
- Use controlled side channels before testing sensitive internal targets.

## Confirmation Discipline

Strong evidence shows backend-originated requests plus meaningful boundary crossing: internal reachability, metadata, credentials, private data, or privileged action. Rule out client-side fetches and public outbound fetch by design without impact.

## References

Read `references/advanced-methodology.md` only when the task needs deeper URL parser review, blind SSRF confirmation, cloud metadata checks, internal service impact, or remediation guidance.
