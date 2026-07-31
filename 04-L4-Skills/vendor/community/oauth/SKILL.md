---
name: oauth
description: Advanced OAuth security testing methodology for bug bounty and application security work. Use when testing or reviewing OAuth 2.0 authorization flows, redirect_uri validation, state or nonce binding, authorization code leakage, token leakage, account linking, OAuth CSRF, provider callback handling, mobile OAuth handoff, IDP/RP trust, email verification claims, token scope mismatch, OAuth SSRF, and open redirect chains leading to account takeover or data access.
---

# OAuth Testing

## Core Posture

Treat OAuth as a chain of bindings: user, client, redirect URI, state, code, token, scope, and account linkage. A flaw in any binding can leak tokens or bind the wrong identity.

## Priority Patterns

- Redirect URI bypass: path traversal, open redirect chains, IDN/homograph, fragment leakage, wildcard subdomains, and URL parser mismatch.
- State/nonce flaws: missing, reusable, cross-session, unbound, or client-side-only state.
- Token/code theft: screenshot viewers, Referer leaks, callback URL parameters, mobile handoff, and trusted subdomain redirects.
- Account linking and email trust: unverified email, forced linking, OAuth CSRF, provider account confusion, and third-party account takeover.
- Scope and client mismatch: overbroad tokens, wrong client, leaked client secrets, and REST/GraphQL scope drift.

## Assessment Loop

1. Map authorization start, provider redirect, callback, token exchange, account creation/linking, and post-login session creation.
2. Track `client_id`, `redirect_uri`, `state`, `nonce`, `code`, token, scope, `aud`, `iss`, and email verification.
3. Test redirect and parser variants before testing account impact.
4. Test linking flows with attacker and victim identities.
5. Confirm leaked code/token, wrong account binding, or unauthorized scope/data access.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| `redirect_uri` | Is matching exact and resistant to redirects/parser tricks? |
| `state` | Is it bound to the initiating session and purpose? |
| Email claim | Is email verified by provider before account merge? |
| Linking | Can A force B to link A's provider account? |
| Token scope | Does token grant more than UI or app promises? |

## Variant Playbook

- Try path traversal, double encoding, mixed case, scheme changes, fragments, userinfo, open redirects, and wildcard subdomains.
- Swap state, nonce, callback, client ID, tenant, and code between sessions.
- Test mobile custom schemes, app links, WebViews, and browser-to-app transitions.
- Check token leakage through Referer, logs, screenshots, redirects, and third-party scripts.
- Compare app scopes, displayed consent, issued token scopes, and API access.

## Confirmation Discipline

Strong evidence shows code/token theft, account linking without intent, wrong-user login, unverified-email takeover, or over-scoped data access. Rule out harmless open redirects outside the OAuth flow.

## References

Read `references/advanced-methodology.md` only when the task needs deeper OAuth flow mapping, redirect validation, state/nonce, token leakage, account linking, confirmation, or remediation checks.
