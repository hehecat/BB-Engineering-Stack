---
name: web-cache
description: Advanced web cache poisoning and cache deception testing methodology for bug bounty and application security work. Use when testing or reviewing cache key confusion, Host header poisoning, CORS header poisoning, CDN cache poisoning, web cache deception, stored XSS through cache, DoS through cache, private data cached publicly, missing Vary headers, path normalization mismatch, origin/CDN disagreement, and workflows where shared caches serve attacker-controlled or private responses to other users.
---

# Web Cache Testing

## Core Posture

Treat cache bugs as key confusion: the cache and origin disagree about which request variants produce distinct responses or whether a response is private.

## Priority Patterns

- Cache poisoning: Host, Origin, headers, path, query, language, and protocol values stored into shared responses.
- Cache deception: private dynamic pages cached as static-like resources.
- CORS cache poisoning: reflected Origin cached for other origins.
- Stored XSS/DoS through poisoned cache entries.
- Private data served cross-user due to missing `Vary: Cookie` or `Vary: Authorization`.

## Assessment Loop

1. Identify cacheable paths, headers, CDN behavior, and cache keys.
2. Test unkeyed inputs that appear in response headers/body.
3. Test private responses for accidental shared caching.
4. Confirm with cache indicators, repeated requests, separate sessions, and controlled cache busters.
5. Assess blast radius by path popularity, TTL, user scope, and stored payload impact.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Unkeyed header | Does response vary without cache key varying? |
| Host/Origin | Can response headers/body be poisoned? |
| Static-looking path | Can private dynamic content be cached? |
| Missing Vary | Are Cookie/Auth/Origin ignored by cache? |
| CDN/origin mismatch | Do they normalize paths differently? |

## Variant Playbook

- Test Host, X-Forwarded-Host, Origin, Accept-Language, path suffixes, query params, cookies, and scheme headers.
- Try encoded paths, semicolons, dots, slashes, case, extensions, and static suffixes.
- Compare anonymous, user A/B, and cache-buster sessions.
- Test TTL, purge behavior, and whether poisoned response reaches another client.

## Confirmation Discipline

Strong evidence shows a shared cache serving attacker-controlled or private content to another user. Rule out browser cache-only effects and uncacheable response reflection.

## References

Read `references/advanced-methodology.md` only when the task needs deeper cache-key review, poisoning, deception, CORS/cache, confirmation, or remediation checks.
