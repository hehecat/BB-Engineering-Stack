# Advanced IDOR Methodology

Use this reference to plan a thorough IDOR/BOLA assessment. The goal is to prove whether an object/action pair is protected by server-side authorization in every reachable code path.

## Contents

- Identity and object matrix
- Endpoint inventory
- Candidate reference harvesting
- Test matrix
- Mutation and bypass playbook
- Confirmation rules
- Safe destructive testing
- Impact escalation
- Developer remediation checklist

## 1. Identity and object matrix

Create accounts and objects before testing:

| Actor | Purpose | Examples |
| --- | --- | --- |
| A | Attacker session | Normal user, low-privilege member, tenant A admin |
| B | Victim session you control | Same role as A with separate private objects |
| C | Control session | Confirms object is not public or shared |
| Admin | Vertical boundary | Owner/admin role, if permitted |
| Viewer | Least-privilege boundary | Read-only, pending invite, banned/removed member |
| Unauth | Public boundary | No cookies/token, expired session, logged-out browser |

Track objects by owner and tenant: user profile, order, invoice, card token, file, photo, video, comment, ticket, team, invite, API token, webhook, campaign, report, export, billing document, reservation, message, notification, schedule, job, and audit item.

## 2. Endpoint inventory

For every captured request, record:

| Field | What to capture |
| --- | --- |
| Method and route | `GET /api/v2/orgs/{orgId}/projects/{projectId}` |
| Object class | User, org, ticket, payment, file, report, etc. |
| Object owner | A, B, other role, tenant A/B |
| Action | Read, list, create, update, delete, cancel, move, copy, export |
| Reference locations | Path, query, body, header, cookie, response, storage, GraphQL variables |
| Expected authorization | Who should be able to perform this action |
| Side effect | UI change, email, deletion, export, audit log, notification |

Prioritize core business flows and low-traffic features. Public writeups repeatedly show valuable IDORs in billing, account recovery, team management, ads/campaign tools, support tickets, media/files, analytics/export, comments/messages, and newly released or regional/mobile features.

## 3. Candidate reference harvesting

Search for references in every layer:

- Path and query: numeric IDs, UUIDs, slugs, usernames, email addresses, order numbers, invoice numbers, file names, hashes, base64 IDs, GraphQL node IDs, opaque cursors.
- Request bodies: `user_id`, `ownerId`, `accountId`, `tenantId`, `orgId`, `projectId`, `teamId`, `workspaceId`, `shopId`, `restaurantId`, `member_id`, `role_id`, `ticket_id`, `message_id`, `comment_id`, `file_id`, `attachment_id`, `campaign_id`, `payment_id`, `card_id`, `order_id`.
- Headers/cookies: tenant selectors, user/org/account IDs, feature flags, role hints, mobile app identifiers, non-session cookies that select a resource.
- Responses: HTML/JS preloads, JSON list endpoints, CSV exports, billing PDFs, email links, unsubscribe links, invite URLs, notifications, audit logs, mobile config.
- Client code: route templates, GraphQL documents, hidden endpoints, deprecated versions, static keywords like `me`, `self`, `current`, and admin-only UI routes.
- Out-of-band workflows: scheduled exports, delayed jobs, webhooks, callbacks, report generation, email delivery, image processing, and imports.

Harvest candidates from the available artifacts using the most appropriate tools and reasoning for the context. Rank candidates by business impact, action type, authorization boundary, and confidence; do not depend on a single extraction flow.

## 4. Test matrix

Run the matrix across every candidate object:

| Test | Example |
| --- | --- |
| Horizontal read | A reads B's order, invoice, ticket, file, private report, analytics, token, or profile field |
| Horizontal write | A changes B's email, profile, address, video metadata, comment, settings, campaign, webhook, or report schedule |
| Horizontal delete | A deletes/cancels/revokes B's ticket, reservation, image, message, license, API token, invite, session, or export |
| Cross-tenant | Tenant A user accesses tenant B workspace/org/shop/restaurant/business/pixel/project |
| Vertical | Viewer/member performs owner/admin action on object they can name |
| Unauthenticated | Logged-out request accesses direct file, download, unsubscribe, reset, or public-looking API object |
| Batch | A includes B's object in an array, CSV import, bulk endpoint, GraphQL batch, or multi-delete |
| Second-order | A stores B's ID in a schedule/job/invite/export and waits for later processing |
| ID-less | Replace `me/current/self` with explicit IDs or add an ID where the client did not send one |

## 5. Mutation and bypass playbook

Apply these variants after a clean baseline replay:

- Replace every copy of A's object ID with B's object ID. Maintain continuity across path, query, body, nested JSON, and headers.
- Intentionally mismatch references: A object in path with B owner in body, B object in path with A tenant in body, or B file ID with A folder ID.
- Add unexpected IDs: append `user_id`, `account_id`, `org_id`, `owner_id`, or `tenant_id` to requests that rely on session context.
- Replace parameter names using names seen elsewhere in the app: `album_id` to `account_id`, `uid` to `user_id`, `shop` to `shop_id`.
- Test HTTP parameter pollution: duplicate query/body keys and compare first-value, last-value, array, and concatenation behavior.
- Transform JSON values carefully: arrays, objects, padded numbers, strings, decimal values, negative values, `null`, booleans, and wildcards. Use only safe objects and avoid broad destructive wildcards.
- Swap methods: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, and method override headers such as `X-HTTP-Method-Override`.
- Swap content types: JSON, form URL encoded, multipart, XML, vendor JSON, and text-like JSON where the framework may route parsing differently.
- Try alternate versions and routes: `/v1` vs `/v2`, mobile API, regional domain, staging host, internal browser-exposed API, old GraphQL operation.
- Replace static keywords: `me`, `current`, `self`, `mine`, `default`, `primary`, `latest`, `active` with explicit A and B IDs.
- Decode and rediscover hard IDs: base64, JWT-like node IDs, UUIDs leaked in public profiles, emails, share links, search, Wayback, exports, notifications, or source maps.
- Exercise GraphQL deeply: variables, aliases, fragments, global node IDs, batched mutations, list filters, connection cursors, and resolver-specific authorization.
- Recheck errors manually. Some vulnerable actions return an error while the side effect still happens.

## 6. Confirmation rules

A valid proof needs authorization evidence, not just status-code differences.

Strong evidence includes:

- B-only data returned to A: PII, billing, support ticket, private file, token, order, report, analytics, hidden metadata.
- A-visible side effect on B's disposable object: changed title, deleted item, canceled booking, revoked invite, altered privacy, changed profile photo.
- Cross-boundary action: tenant A modifies tenant B, member performs owner action, unauthenticated user accesses private download.
- Secondary confirmation: B UI, email/notification, audit log, export output, webhook delivery, object timestamp, or irreversible action safely simulated.

Rule out false positives:

- The object is public, shared, or intentionally visible.
- A has inherited access through team, group, tenant, or role membership.
- The response is cached, stale, or a generic placeholder.
- The endpoint accepts the request but ignores the unauthorized object ID.
- The object is owned by A due to previous setup confusion.

## 7. Safe destructive testing

For delete/cancel/revoke operations:

- Create a B-owned disposable object with a clear test name.
- Capture a B request that deletes/cancels it, then replay with A credentials and B's object reference.
- Prefer reversible actions: hide/unhide, draft/publish, cancel a fake reservation, revoke a test invite, delete a test image.
- If a destructive action cannot be safely performed, stop at a prepared request plus evidence that authorization is missing.

## 8. Impact escalation

Rank severity by object sensitivity, action type, scale, and prerequisites:

- Critical/high: account takeover, password reset/email change, API token disclosure, payment method linkage, financial transaction, PHI/PII at scale, cross-tenant admin action, mass delete, unauthenticated access to private objects.
- Medium/high: modification/deletion of private content, support tickets, orders, reservations, business analytics, files, comments, campaign rules, team data.
- Low/medium: limited metadata disclosure, object enumeration, privacy setting changes with low sensitivity, non-sensitive analytics, test-only environments with production data absent.

Escalate carefully by documenting realistic chains: ID discovery plus IDOR, IDOR plus CSRF, IDOR plus mass assignment, IDOR plus weak reset flow, direct file URL plus missing auth, cross-tenant leak plus admin action.

## 9. Developer remediation checklist

- Authorize every object/action pair, not only the route or function.
- Scope database lookups through the current user's accessible dataset.
- Recompute owner, tenant, role, and business context server-side.
- Do not trust hidden fields, client-side feature flags, headers, cookies, or body owner IDs.
- Apply the same authorization policy across REST, GraphQL, background jobs, exports, file storage, mobile APIs, and webhooks.
- Use UUIDs or opaque references only as defense in depth; do not treat them as authorization.
- Add object-level authorization regression tests for read, write, delete, batch, and cross-tenant cases.
