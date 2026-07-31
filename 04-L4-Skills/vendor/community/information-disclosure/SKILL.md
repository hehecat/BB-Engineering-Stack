---
name: information-disclosure
description: Advanced information disclosure testing methodology for bug bounty and application security work. Use when testing or reviewing sensitive data leaks, private user data exposure, debug or Sentry leaks, directory listing, cache disclosure, deeplink data leakage, internal metadata, hidden IDs, stack traces, source maps, logs, backups, unauthenticated endpoints, and API, mobile, web, or infrastructure responses that reveal data beyond the intended audience.
---

# Information Disclosure Testing

## Core Posture

Treat information disclosure as an audience mismatch: data intended for one user, role, tenant, environment, or internal system is exposed to another.

## Priority Patterns

- User data: email, phone, address, private profile, read status, resumes, tickets, tax docs, billing, and private content.
- Internal data: stack traces, Sentry events, source maps, configs, logs, error messages, internal paths, private program metadata, and service names.
- Public directories and backups: unsecured attachments, uploads, buckets, build artifacts, old files, and debug dumps.
- Cache and deeplink leaks: poisoned/shared cache, mobile deeplinks, notification previews, referers, and URL tokens.
- API overexposure: fields returned to low roles, hidden IDs, internal identifiers, and nested GraphQL/API object leaks.

## Assessment Loop

1. Inventory responses across users, roles, tenants, unauthenticated state, mobile, API, and error paths.
2. Classify every field by sensitivity and intended audience.
3. Compare list/detail/search/export/mobile/debug responses for field drift.
4. Test stale, deleted, private, unverified, and cross-tenant objects.
5. Confirm whether disclosed data enables privacy harm, chaining, enumeration, auth bypass, or business impact.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Extra fields | Does the client receive data it does not render? |
| Debug/error | Are stack traces, configs, logs, or internal IDs exposed? |
| Directory/bucket | Are uploads, backups, or attachments browseable? |
| Cache/deeplink | Can private data leak through shared cache, notification, or URL? |
| Metadata | Does "low sensitivity" data reveal private targets or program state? |

## Variant Playbook

- Compare A/B users, tenant A/B, public/private objects, web/mobile/API clients, and list/detail/export endpoints.
- Add `format=json`, `.json`, `?debug`, old API versions, regional hosts, and mobile endpoints.
- Trigger errors with invalid IDs, types, auth, and malformed inputs.
- Inspect HTML preloads, JavaScript bundles, local storage, source maps, logs, and exported files.
- Check cache headers and whether private responses are stored or replayed.

## Confirmation Discipline

Strong evidence shows sensitive data exposed to an unintended audience. Rule out intentionally public data, self-owned objects, harmless IDs with no chaining value, and data already visible through the same role.

## References

Read `references/advanced-methodology.md` only when the task needs deeper field classification, debug leak review, cache/deeplink review, API overexposure checks, confirmation, impact ranking, or remediation guidance.
