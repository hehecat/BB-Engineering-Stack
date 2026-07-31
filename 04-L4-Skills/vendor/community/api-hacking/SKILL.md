---
name: api-hacking
description: Advanced API security testing methodology for bug bounty and application security work. Use when testing or reviewing REST APIs, GraphQL APIs, mobile APIs, internal or undocumented APIs, exposed infrastructure APIs, API key or token leaks, broken API authentication or authorization, BOLA/IDOR, sensitive response data, CORS/cache/CSRF flaws, SSRF through preview/export APIs, injection through API parameters, cloud or Kubernetes/Docker/control-plane APIs, webhook/callback APIs, and API-driven account, tenant, admin, file, billing, or operational workflows.
---

# API Security Testing

## Core Posture

Treat API hacking as trust-boundary testing. Identify who can call an endpoint, what identity or token the server trusts, what object or tenant is affected, what parser or backend receives the input, and what side effect or data exposure results.

Use public case lessons as prioritization signals, not as a fixed recipe. Choose inspection methods from the user's artifacts and target type. Do not narrow the skill to REST alone; include GraphQL, mobile, internal, cloud, control-plane, callback, and background-job APIs.

## Priority Patterns

Prioritize APIs that expose secrets, cross boundaries, or control infrastructure:

- Secret and token exposure: API keys in GitHub repos, JavaScript, mobile apps, docs, old commits, Postman collections, logs, error messages, cloud configs, and sample code.
- Exposed control-plane APIs: Kubernetes API, Docker Registry API, Flink APIs, Spring Actuator, pprof/debug endpoints, Cortex/metrics APIs, Jira/Phabricator/admin APIs, cloud service APIs, and internal panels.
- Broken API authentication lifecycle: banned, deleted, deactivated, expired-password, removed-member, and revoked-token states that still work through API keys, mobile endpoints, or old clients.
- Broken object or tenant access: private videos, emails, user PII, family pairing, deploy keys, private repositories, uploads, files, bounties, support data, billing, analytics, and GraphQL object IDs.
- GraphQL abuse: undocumented mutations, resolver-specific authorization gaps, mutation aliasing DoS, overbroad token scopes, nested object leaks, schema drift, and REST/GraphQL state races.
- SSRF and callback abuse: preview links, export APIs, webhook targets, URL importers, image/file converters, game/export features, and redirect-following backends.
- Injection and parser abuse: SQLi, command/flag injection, path traversal, stored XSS through API content, converter/rendering APIs, JSON/XML parser quirks, and method override behavior.
- CORS, cache, and CSRF: reflected Origin headers, cacheable CORS responses, JSON CSRF, cross-site state-changing API calls, missing `Vary`, and private API data cached across users.
- Sensitive response data: OTP codes, hashed passwords, client secrets, server tokens, private email, read receipts, internal paths, hidden IDs, admin data, and internal identifiers.
- Availability and cost abuse: infinite loops, mutation aliasing, expensive queries, unbounded decompression, unrestricted exports, quota-burning API keys, and rate-limit bypasses.

## Assessment Loop

1. Build an API inventory: REST routes, GraphQL operations, mobile endpoints, internal hosts, staging/non-production APIs, docs, SDKs, JavaScript bundles, app bundles, webhooks, callbacks, and background jobs.
2. Map identities and credentials: anonymous user, normal user, elevated role, tenant admin, removed/banned user, expired user, API key, OAuth token, mobile token, service token, leaked key, and internal token.
3. Classify each endpoint by asset and action: read, list, search, create, update, delete, copy, export, import, render, preview, webhook, invite, billing, admin, debug, metrics, and job control.
4. Track trust inputs: path IDs, query fields, JSON/body fields, GraphQL variables, headers, cookies, Origin, Host, callback URLs, file names, tokens, tenant selectors, and method overrides.
5. Establish a normal baseline, then test boundary swaps: wrong user, wrong tenant, wrong role, removed state, stale token, unauthenticated request, internal-looking header, and mobile-vs-web client.
6. Exercise parser and transport variants: method changes, duplicate parameters, content-type swaps, batch requests, GraphQL aliases, nested objects, redirects, cache keys, and webhook/callback delivery.
7. Confirm impact through returned data, durable state change, privilege escalation, secret validity, backend reachability, operational control, cost impact, or service degradation.

## High-Value Cues

| Family | Look for | Ask |
| --- | --- | --- |
| Leaked secrets | API key, token, client secret, certificate, webhook secret, cloud key | Is the secret valid, over-scoped, unrevoked, or tied to production data? |
| Control-plane APIs | Kubernetes, Docker Registry, Flink, Actuator, pprof, metrics, Jira, Phabricator | Can the API reveal config, creds, jobs, images, debug data, or admin actions? |
| Token lifecycle | banned/deleted user, revoked key, removed member, expired password, old mobile token | Does API access survive a state that should remove access? |
| Object access | `user_id`, `file_id`, `video_id`, `repo`, `team_id`, `tenantId`, `shopId` | Does the API authorize the object/action pair server-side? |
| GraphQL | operation names, variables, aliases, fragments, node IDs, batch requests | Are resolvers and mutations checked as strictly as REST routes? |
| SSRF/callback | URL preview, export, webhook, importer, converter, avatar fetch, redirect | Can the backend be made to fetch internal or attacker-observed resources? |
| Injection | search, render, import, converter, file path, command flags, SQL filters | Does user input cross into shell, Git, SQL, filesystem, XML, template, or renderer contexts? |
| Response leakage | OTP, password hash, private email, internal ID, server token, read status | Is sensitive data returned to a client that does not need it? |
| CORS/cache/CSRF | Origin reflection, missing `Vary`, cacheable API, JSON POST, weak headers | Can browsers or caches make private API state visible or mutable cross-site? |
| DoS/cost | aliasing, loops, exports, decompression, expensive search, maps/geocode keys | Can a small request trigger high CPU, memory, quota, billing, or storage impact? |

## Variant Playbook

- Replay requests across identities, roles, tenants, tokens, client types, and account states.
- Replace object and tenant references across path, query, body, headers, cookies, and GraphQL variables.
- Try unauthenticated, stale-token, revoked-token, banned-user, deleted-user, expired-password, and removed-member states.
- Compare web, mobile, legacy, regional, staging, internal-browser, and documented API routes for the same action.
- Check whether secrets from code, JS, mobile apps, docs, commits, or API responses can authenticate and what they can access.
- Exercise GraphQL with aliases, fragments, batching, nested selections, stale operation names, resolver-specific IDs, and REST/GraphQL races.
- Probe URL-fetching APIs for redirect behavior, scheme handling, host allowlists, DNS rebinding assumptions, and internal response side channels.
- Test parser differences: JSON vs form vs multipart, duplicate keys, arrays, objects, strings vs numbers, XML, vendor JSON, and method override headers.
- Review cache behavior around authenticated API responses, CORS headers, `Vary`, CDN keys, cookies, authorization headers, and Origin reflection.
- Verify rate limits and resource controls on search, export, render, import, aliasing, decompression, and expensive aggregation endpoints.

## Confirmation Discipline

A useful API finding needs impact evidence, not just a surprising status code.

Strong evidence includes:

- Sensitive data returned: PII, OTP, private email, private file, token, hashed password, internal config, admin data, billing, or private repository data.
- Authorization boundary crossed: wrong user, tenant, role, client, account state, or token state succeeds.
- Valid leaked secret: the key reaches real data, paid APIs, cloud resources, admin panels, write actions, or operational APIs.
- Backend reachability: SSRF/callback behavior proves the server fetched an internal, private, or attacker-observed resource.
- Operational control: API can create admin users, modify permissions, copy files, poison images, run jobs, access debug profiles, or alter infrastructure state.
- Availability or cost impact: small requests cause expensive work, quota burn, cache poisoning, long loops, memory pressure, or service degradation.

Rule out weak findings:

- The API key is public by design and correctly restricted by origin, service, quota, and permission.
- The endpoint returns only intentionally public metadata.
- The object is shared, public, or inherited through legitimate membership.
- The token is revoked, test-only, low-privilege, or restricted to harmless operations.
- A request succeeds but ignores the unauthorized object or state-changing field.
- Debug, staging, or non-production data has no useful secrets, privileges, production linkage, or operational impact.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper API inventory, credential review, GraphQL matrix, control-plane checklist, SSRF/callback review, cache/CORS/CSRF review, injection review, confirmation checklist, impact ranking, or remediation checklist.
