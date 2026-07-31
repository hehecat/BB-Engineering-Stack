---
name: csrf
description: Advanced CSRF testing methodology for bug bounty and application security work. Use when testing or reviewing cross-site request forgery, missing or weak CSRF tokens, SameSite cookie gaps, JSON CSRF, OAuth or linked-account CSRF, deeplink CSRF, state-changing API endpoints, payment provider linking, account settings changes, admin console actions, and any workflow where a browser can be tricked into sending authenticated state-changing requests.
---

# CSRF Testing

## Core Posture

Treat CSRF as a confused-browser problem: the browser supplies credentials, while the server fails to verify user intent and request origin for a state-changing action.

## Priority Patterns

- Linked accounts, OAuth grants, payment provider connections, integrations, and webhooks.
- Email, password, 2FA, profile, privacy, and account recovery settings.
- Admin console actions, enterprise management, user invites, role changes, and feature toggles.
- Mobile deeplinks and app-to-web transitions.
- JSON APIs, method override, simple content types, and missing preflight assumptions.

## Assessment Loop

1. Inventory state-changing actions and classify impact.
2. Identify auth mechanism: cookie, bearer token, basic auth, client cert, or mixed auth.
3. Check CSRF token, Origin/Referer validation, SameSite behavior, CORS, and content type.
4. Try cross-site delivery through forms, images, scripts, fetch where allowed, deeplinks, redirects, and top-level navigations.
5. Confirm the side effect under victim credentials.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Cookie-auth API | Can a simple form or navigation trigger it? |
| Token mismatch | Is the token missing, reusable, unbound, or accepted from another session? |
| JSON endpoint | Can content-type or method override avoid preflight/token checks? |
| OAuth/linking | Can A force B to link A's account or approve a grant? |
| SameSite edge | Does top-level GET/POST, legacy browser, or subdomain flow bypass protection? |

## Variant Playbook

- Remove token, reuse old token, swap token between accounts, duplicate token, or place token in another parameter.
- Test `GET`, `POST`, method override, form URL encoded, multipart, text/plain JSON, and JSON with simple preflight behavior.
- Try missing/forged Origin and Referer, same-site subdomain, null origin, and redirect chains.
- Test endpoints behind mobile deeplinks, OAuth callbacks, and admin consoles.
- Verify whether token checks happen before or after side effects.

## Confirmation Discipline

Strong evidence is a state change caused cross-site with victim credentials. Rule out actions that require attacker-readable response only, endpoints protected by bearer tokens unavailable to the browser, or changes that the server ignores.

## References

Read `references/advanced-methodology.md` only when the task needs deeper SameSite, token, CORS, JSON CSRF, OAuth/linking, deeplink, or remediation checks.
