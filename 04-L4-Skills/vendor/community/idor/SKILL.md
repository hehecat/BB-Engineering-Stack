---
name: idor
description: Advanced IDOR/BOLA testing methodology for bug bounty and application security work. Use when testing or reviewing insecure direct object references, broken object-level authorization, cross-tenant access, account/member takeover through object IDs, payment/order/billing data exposure, destructive object mutations, GraphQL object authorization flaws, private file or export access, support/ticket/message/event authorization issues, or HTTP/API traffic with object identifiers in URL paths, query strings, JSON/form/multipart bodies, GraphQL variables, headers, cookies, mobile APIs, internal APIs, hidden features, and second-order workflows.
---

# IDOR/BOLA Testing

## Core posture

Treat IDOR as an object/action authorization failure, not as a simple parameter swap. Test whether the server verifies that the current caller may perform the exact action on the exact object in the exact tenant, role, state, and workflow.

Use public case lessons as prioritization signals, not as a fixed recipe. Choose inspection methods from the user's artifacts and target type. Do not narrow the skill to one artifact type or extraction routine.

## Priority Patterns

Prioritize business impact over obvious URLs. Focus first on object references attached to high-impact workflows:

- Account and relationship control: adding secondary users, linking credit cards, editing team users, changing profile or email data, deleting accounts, expiring sessions, viewing API tokens, moving objects between users, and changing permissions.
- Money and commerce: payment orders, billing documents, invoices, card identifiers, checkout objects, reservations, booking cancellations, order delivery addresses, price manipulation, payment status, and provider confirmation payloads.
- Destructive or state-changing actions: deleting certifications, campaigns, tickets, messages, email addresses, featured photos, images, albums, invites, licenses, reservations, and technical badges.
- GraphQL object authorization: operation names, variables, input IDs, global node IDs, aliases, batched operations, resolver-specific arguments, and mutations that create, update, delete, move, link, or export objects.
- Cross-tenant business objects: organization, business, workspace, shop, restaurant, team, pixel, campaign, product, loyalty, analytics, and internal account selectors.
- Private data and analytics: private report details, payment data, PII, emails, phone numbers, order information, mod logs, restaurant analytics, machine learning models, team membership data, and social/ad-service tokens.
- Files, media, attachments, and exports: direct download URLs, attachment IDs, image/video metadata, gallery and album objects, profile photos, CSV/PDF exports, converted files, and scheduled reports.
- Edge surfaces: unreleased features, hardcoded mobile endpoints, internal APIs exposed to browsers, regional/staging/non-production hosts, old API versions, and hidden client-side routes.

## Assessment Loop

1. Define the authorization boundary: user-to-user, member-to-admin, tenant-to-tenant, authenticated-to-unauthenticated, public-to-private, active-to-removed, or pending-to-accepted.
2. Build an identity matrix: attacker A, victim B, optional control C, roles such as owner/admin/member/viewer, separate tenants or workspaces, and logged-out or expired-session states.
3. Create owned objects for each account: profile fields, files, orders, tickets, messages, campaigns, reports, exports, billing objects, invites, API tokens, and disposable delete targets.
4. Capture complete feature flows, not only endpoints: read, list, create, edit, move, link, unlink, invite, approve, cancel, revoke, hide, publish, export, download, delete, and background jobs.
5. Harvest references from every layer: paths, queries, request bodies, nested JSON, GraphQL variables, headers, cookies, response preloads, client storage, JS bundles, mobile traffic, emails, notifications, exports, and audit logs.
6. Establish a clean baseline with the correct identity and object, then replay the same action with the wrong identity and the victim-owned object.
7. Expand only after the baseline: try role changes, tenant changes, state changes, content-type and method variants, path/body mismatches, duplicate parameters, array or object wrapping, explicit IDs for `me/current/self`, and alternate API versions.
8. Confirm with evidence that crosses the intended boundary: B-only data returned to A, a side effect visible in B's account, a changed export, a notification, an audit log entry, or successful access after removal or logout.

## High-Value Cues

Use these cues to decide where to spend attention:

| Family | Look for | Ask |
| --- | --- | --- |
| Add/link/takeover | `user_id`, `member_id`, `business_id`, `team_id`, invite IDs, card IDs, API app IDs | Can A add themselves, link a resource, change a role, or bind another user's object to A? |
| Payment/order/billing | orders, invoices, checkout IDs, payment confirmations, reservations, card tokens, price fields | Can A view, alter, cancel, or pay using B's financial or commerce object? |
| GraphQL | operation names, variables, global node IDs, mutation inputs, connection cursors | Does each resolver authorize the object, or only the session and operation? |
| Destructive actions | delete/cancel/revoke/hide/unpublish/remove endpoints and mutations | Can A affect B's disposable object even if the response is generic or errors? |
| Cross-tenant | `orgId`, `tenantId`, `businessId`, `workspaceId`, `shopId`, `restaurantId`, `pixelId` | Does the server recompute tenant context, or trust client-supplied selectors? |
| Files/media/exports | attachment IDs, file IDs, direct URLs, conversion jobs, CSV/PDF exports, profile image IDs | Can A download, replace, convert, delete, or disclose metadata from B's private file? |
| Support/social/state | tickets, messages, comments, events, mod logs, leave/ban states, feedback objects | Does access persist after leaving, being banned, losing role, or changing state? |
| Hidden surfaces | unreleased UI, internal API, mobile-only route, staging or regional host, legacy version | Did a less-used code path skip the policy check used by the main UI? |

## Variant Playbook

- Replace every occurrence of A's object reference with B's equivalent across path, query, body, nested JSON, headers, cookies, and GraphQL variables.
- Mismatch related IDs: B object with A tenant, A folder with B file, B campaign with A account, or B member with A role.
- Add IDs to requests that appear session-derived: `user_id`, `ownerId`, `accountId`, `orgId`, `tenantId`, `profileId`, `member_id`, and `business_id`.
- Rename parameters using vocabulary already present elsewhere in the app, such as `uid`, `owner`, `account`, `shop`, `member`, `actor`, `subject`, or `resource`.
- Test duplicate keys, arrays, object wrapping, string-vs-number values, `null`, empty strings, padded numbers, and safe boundary values.
- Swap methods and parsers: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, method override headers, JSON, form URL encoded, multipart, vendor JSON, and text-like JSON.
- Test GraphQL aliases, fragments, batches, old operation names, global node IDs, resolver-specific IDs, list filters, and connection cursors.
- Test lifecycle states: invited, pending, removed, banned, left group, canceled, archived, hidden, deleted, expired session, disabled user, and read-only role.
- Test second-order flows: scheduled exports, report generation, email delivery, webhooks, imports, file conversion, async jobs, notifications, and audit logs.

## Confirmation Discipline

A status code is not proof. Confirm whether the unauthorized object was read, changed, deleted, linked, moved, exported, emailed, billed, or otherwise acted on.

For destructive flows, prefer reversible or disposable proof objects such as hide/unhide, draft/publish, cancel a test booking, revoke a test invite, or delete a test image. If direct proof is not practical, document the prepared request plus strong evidence that the server trusts the unauthorized object reference.

Rule out false positives:

- The object is intentionally public, shared, inherited, or visible through team membership.
- The request succeeds but ignores the unauthorized object.
- The response is cached, generic, stale, or from A's own object.
- B granted access through another role, tenant, workspace, invite, or previous setup.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper identity matrix, endpoint inventory, variant matrix, confirmation checklist, impact ranking, or remediation checklist.
