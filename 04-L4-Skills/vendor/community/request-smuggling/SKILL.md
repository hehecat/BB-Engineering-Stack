---
name: request-smuggling
description: Advanced HTTP request smuggling and desync testing methodology for bug bounty and application security work. Use when testing or reviewing front-end/back-end HTTP parser disagreement, CL.TE or TE.CL issues, HTTP/2 downgrading, proxy desync, cache poisoning through desync, credential or token theft, response queue poisoning, request tunneling, internal endpoint access, and chains where malformed HTTP framing crosses authentication, routing, or cache boundaries.
---

# Request Smuggling Testing

## Core Posture

Treat request smuggling as parser disagreement between intermediaries and origin. The impact comes from what boundary the desync crosses: session, cache, routing, auth, internal endpoint, or another user's response.

## Priority Patterns

- Token/session theft through response queue poisoning.
- Auth bypass or internal routing on admin/API hosts.
- Cache poisoning and stored response poisoning.
- Bulk user impact on shared high-traffic hosts.
- HTTP/2 to HTTP/1 downgrade issues and duplicate/ambiguous framing headers.
- Login/password theft and request prefix injection.

## Assessment Loop

1. Identify proxy/CDN/load balancer/origin stack and HTTP versions.
2. Test safe desync indicators before impact payloads.
3. Explore CL.TE, TE.CL, TE.TE, HTTP/2 downgrade, duplicate headers, whitespace, and casing variants.
4. Determine whether desync affects your own connection, shared backend, cache, or victim traffic.
5. Confirm impact with controlled requests, canaries, or isolated accounts.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Shared proxy | Can one request affect another user's response? |
| Auth host | Can smuggled prefix reach authenticated endpoints? |
| Cache | Can desync poison a cache key or body? |
| H2 downgrade | Do HTTP/2 pseudoheaders become ambiguous HTTP/1? |
| Login flow | Can credentials or tokens be reflected into attacker response? |

## Variant Playbook

- Test conflicting `Content-Length` and `Transfer-Encoding` values, duplicate headers, obs-fold-like spacing, and casing.
- Compare HTTP/1.1, HTTP/2, CDN, direct origin, and alternate hosts.
- Use canary paths and low-risk response markers.
- Test cacheable and authenticated paths separately.
- Avoid uncontrolled high-volume victim interaction.

## Confirmation Discipline

Strong evidence shows desync plus impact: token theft, cache poisoning, auth bypass, internal request routing, or cross-user response contamination. Rule out scanner-only anomalies without boundary crossing.

## References

Read `references/advanced-methodology.md` only when the task needs deeper parser variant review, HTTP/2 downgrade checks, cache/auth chaining, confirmation, or remediation guidance.
