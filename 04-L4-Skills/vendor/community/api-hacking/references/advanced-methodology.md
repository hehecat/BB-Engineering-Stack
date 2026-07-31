# API Hacking Methodology

Use this reference to plan a thorough API security assessment. The goal is to understand every API trust decision: caller identity, credential, object, tenant, input parser, backend service, side effect, and returned data.

## Contents

- API inventory
- Identity and credential matrix
- Endpoint action model
- Secret exposure review
- Authentication and authorization matrix
- GraphQL methodology
- SSRF and callback API review
- Injection and parser review
- CORS, cache, and CSRF review
- Control-plane and infrastructure API review
- Confirmation rules
- Impact ranking
- Developer remediation checklist

## 1. API inventory

Collect API surfaces from:

- Browser traffic, HAR files, API docs, OpenAPI/Swagger specs, SDKs, GraphQL documents, JavaScript bundles, source maps, and client storage.
- Mobile traffic, app bundles, deeplinks, feature flags, hardcoded hosts, embedded API keys, and old app versions.
- Public repos, old commits, CI logs, Postman collections, examples, docs, support articles, package metadata, and archived URLs.
- Internal-looking hosts exposed to the browser: admin, metrics, ingest, debug, staging, regional, preview, upload, render, webhook, callback, and non-production endpoints.
- Background APIs: exports, imports, converters, previews, file copy, image renderers, scheduled jobs, notifications, analytics, and billing jobs.

Record route, method, host, auth type, client type, action, object class, tenant selector, response sensitivity, side effects, cache headers, and observed error behavior.

## 2. Identity and credential matrix

Test with distinct states:

| State | Purpose |
| --- | --- |
| Anonymous | Missing-auth and public data boundary |
| Normal user A/B | Horizontal object and privacy boundary |
| Tenant A/B | Cross-org, workspace, shop, project, team, and business boundary |
| Viewer/member/admin | Vertical role boundary |
| Removed/banned/deleted | Lifecycle and token revocation boundary |
| Expired password/session | Session and stale-token boundary |
| API key/OAuth token | Machine access and scope boundary |
| Mobile token | Client-specific access boundary |
| Leaked credential | Real impact and scope validation |
| Internal/service token | Admin, service-to-service, and control-plane boundary |

Track credential type, owner, issued time, scope, tenant, client, storage location, revocation behavior, and whether UI access differs from API access.

## 3. Endpoint action model

Classify actions by impact:

- Read/list/search: user profile, private email, private video, repository, upload, message, ticket, billing, analytics, status, logs.
- Create/copy/import/export: file copy, bounty creation, report export, data import, image conversion, game export, webhook registration.
- Update/delete: profile, family pairing, group name, settings, token settings, admin users, API keys, comments, messages.
- Operational control: start jobs, plan jobs, run renderers, call debug endpoints, read configs, list containers/images, poison registries, access metrics.
- Security control: OTP generation, email verification, CSRF token, password reset, account ban, token revocation, permission enumeration.

Prioritize actions with write access, secret exposure, tenant boundary impact, admin effect, operational control, or large-scale enumeration.

## 4. Secret exposure review

Search client and public artifacts for:

- API keys, OAuth client secrets, server tokens, API tokens, certificates, private keys, webhook secrets, basic auth, cloud access keys, and service URLs.
- Keys in JavaScript, Android/iOS bundles, old commits, docs, Postman collections, support snippets, error messages, GraphQL responses, and internal APIs.
- Keys that look public but are misconfigured: unrestricted Google Maps/Geocode/Firebase, Cloudinary secrets in mobile apps, Jira tokens, Datadog keys, JumpCloud keys, or sample API tokens.

Validate by asking:

- Does the key authenticate to live data or paid services?
- Is it restricted by origin, IP, app, bundle ID, service, quota, tenant, and permission?
- Can it read, write, delete, enumerate, administer, or create users?
- Does revocation actually remove access across REST, GraphQL, mobile, and legacy APIs?

## 5. Authentication and authorization matrix

For each endpoint:

- Remove auth and compare response, cache behavior, error shape, and side effects.
- Replay with A against B's object and tenant.
- Replay with viewer/member against admin-only object or action.
- Replay with removed, banned, deleted, expired, or revoked-token states.
- Replay with API key vs browser cookie vs mobile token vs OAuth token.
- Add or change tenant selectors, owner IDs, role IDs, account IDs, object IDs, and feature flags.
- Compare REST and GraphQL implementations of the same action.

Watch for UI-only enforcement, server trust in client-supplied tenant/owner fields, stale API keys, hidden mobile APIs, and role checks that apply to list views but not direct object fetches.

## 6. GraphQL methodology

Inspect:

- Operation names, variables, aliases, fragments, node IDs, global IDs, connection cursors, nested selections, and batching.
- Undocumented mutations and old operation names still accepted by the server.
- Resolver-specific authorization: parent object may be authorized while nested fields are not.
- Scope mismatch: token scope allows REST-limited access but GraphQL returns more.
- Mutation aliasing and batching that multiply expensive work.
- REST/GraphQL races where one path updates permissions while another path retains access.

Confirm that every resolver enforces caller, object, tenant, role, and lifecycle state; do not assume the top-level route policy protects nested fields.

## 7. SSRF and callback API review

Review APIs that fetch attacker-influenced URLs:

- Link preview, media preview, export, import, webhook, callback, avatar fetch, game export, PDF/image converter, document renderer, and URL shortener.
- URL fields hidden in nested JSON, metadata, GraphQL variables, multipart file metadata, and callback registration.
- Redirect handling, scheme allowlists, DNS behavior, IPv6, localhost aliases, cloud metadata assumptions, and parser differences.
- Blind side channels: timing, error message, content title, status text, image dimensions, webhook hits, DNS hits, and response size.

Focus on proof of backend reachability and boundary crossing, not broad scanning.

## 8. Injection and parser review

Review parameters that cross into interpreters or parsers:

- Search APIs, Git/blob search, SQL filters, analytics query APIs, GraphQL filters, template renderers, markdown renderers, image/SVG/Graphie converters, import/export paths, file names, archive paths, and command flags.
- Content-type differences: JSON, form, multipart, XML, vendor JSON, text-like JSON, and method override headers.
- Duplicate parameter handling, array/object wrapping, type confusion, nulls, empty strings, large numbers, booleans, and encoded separators.
- Stored API content later rendered in admin, backend, mobile, email, or export contexts.

Look for parser confusion that converts API input into SQL, shell flags, filesystem paths, renderer content, HTML/JS, XML entity processing, or backend job arguments.

## 9. CORS, cache, and CSRF review

Review browser-mediated API trust:

- Reflected `Origin`, wildcard CORS with credentials, missing `Vary: Origin`, cacheable CORS headers, and inconsistent preflight behavior.
- API responses with private data but weak cache headers, missing `Vary: Cookie` or `Vary: Authorization`, CDN key confusion, and poisoned shared cache entries.
- JSON CSRF on state-changing endpoints, simple content types, method override, weak Origin/Referer validation, SameSite gaps, and legacy Flash or form-based request paths.
- Token-bearing pages or API docs that are cacheable or served from shared origins.

Confirm whether the browser, cache, or CDN can make private API data readable or state-changing requests triggerable across origins.

## 10. Control-plane and infrastructure API review

Prioritize exposed APIs that manage infrastructure or operations:

- Kubernetes API, Docker Registry v2, container image registries, Flink job APIs, Spring Actuator, pprof/debug endpoints, metrics/ingest APIs, CI/CD APIs, cloud service APIs, admin panels, Jira, Phabricator, and monitoring systems.
- Read-only endpoints that reveal credentials, command-line arguments, environment variables, service discovery, tokens, internal paths, image names, logs, configs, or stack traces.
- Write-capable endpoints that create jobs, upload images, alter configs, poison artifacts, create admin users, revoke tokens, or change permissions.
- Non-production endpoints that touch production data, production credentials, production logs, or cloud audit behavior.

Treat "debug", "metrics", "ingest", "staging", and "internal" as high-priority words when they appear on public hosts or browser-reachable routes.

## 11. Confirmation rules

Strong API impact evidence includes:

- Live sensitive data returned to the wrong identity.
- A valid secret reaches protected data, write actions, admin panels, paid APIs, or cloud/control-plane resources.
- API access survives account deletion, ban, token revocation, membership removal, password expiry, or tenant change.
- A backend fetch reaches internal, private, or attacker-observed infrastructure.
- API input reaches an interpreter, renderer, command, SQL query, filesystem path, or background job.
- A low-privilege user creates admin users, changes permissions, copies protected files, reads private repositories, poisons images, or starts jobs.
- A small request causes meaningful quota, CPU, memory, storage, cache, or availability impact.

Rule out false positives:

- Public keys are correctly restricted and cannot reach sensitive services or cost impact.
- The returned data is intentionally public or already visible to the same identity.
- A successful response ignores the unauthorized object, tenant, or state-changing input.
- The endpoint is non-production with no production data, credentials, privilege, or realistic impact.
- SSRF behavior cannot reach anything beyond intentionally public outbound fetches.
- CORS is permissive but credentials are absent and private data is not exposed.

## 12. Impact ranking

Rank severity by boundary crossed, control gained, data sensitivity, scale, and prerequisites:

- Critical: exposed Kubernetes/Docker/control-plane API with secrets or write capability, valid production admin/service token, API-driven RCE, mass private-data disclosure, API key enabling admin creation, or SSRF to high-value internal services.
- High: private user data at scale, cross-tenant access, stale API key after ban/deletion, GraphQL token-scope breakout, sensitive internal config disclosure, stored XSS reaching admins, or CSRF enabling account/security changes.
- Medium: limited PII disclosure, private metadata leaks, read-only internal debug data, paid API quota abuse, restricted key misuse, or denial of service with moderate prerequisites.
- Low: low-sensitivity metadata, public-key exposure with weak cost impact, non-production only with no production linkage, or behavior requiring unrealistic setup.

## 13. Developer remediation checklist

- Keep secrets out of client-side code, public repos, app bundles, docs, logs, and API responses.
- Scope API keys by service, tenant, environment, IP/origin/app, permission, quota, and expiration.
- Revoke and rotate keys on user ban, deletion, role removal, tenant removal, password expiry, incident response, and suspected leak.
- Enforce server-side object, tenant, role, lifecycle, and token-scope authorization on every REST route and GraphQL resolver.
- Disable or protect control-plane, debug, metrics, registry, actuator, pprof, and non-production APIs.
- Validate URL-fetching APIs with strict schemes, hosts, DNS/IP handling, redirect policy, and egress controls.
- Apply defensive cache headers to private API responses and set correct `Vary` headers.
- Protect state-changing APIs from CSRF and browser-mediated abuse.
- Bound expensive API operations with rate limits, query cost, pagination, depth limits, timeouts, and resource quotas.
- Add regression tests for auth states, stale tokens, cross-tenant access, GraphQL resolvers, cache/CORS behavior, SSRF filters, and secret revocation.
