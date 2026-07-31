# Authorization Bypass Methodology

Use this reference to plan a thorough authorization bypass and privilege escalation assessment. The goal is to prove whether the server enforces role, object, tenant, workflow, identity-verification, and privilege boundaries for every reachable path.

## Contents

- Principal and role matrix
- Object, tenant, and workflow inventory
- Email verification, SSO, and invite checks
- Role and permission escalation checks
- GraphQL and API authorization checks
- Business workflow bypass checks
- Admin, debug, and infrastructure surface checks
- Local, container, and root privilege escalation checks
- Confirmation rules
- Impact ranking
- Developer remediation checklist

## 1. Principal and role matrix

Track principals and states:

| Principal or state | Purpose |
| --- | --- |
| Anonymous | Public-to-private boundary |
| Normal user A/B | Horizontal user boundary |
| External user | Outsider-to-organization boundary |
| Invited user | Invite acceptance and pending state |
| Viewer/member/staff | Vertical role boundary |
| Program-only or limited role | Hidden permission and partial-admin boundary |
| Admin/owner | High-privilege baseline |
| SSO user | Domain and IdP trust boundary |
| Service/integration user | API token and generated-session boundary |
| Tenant A/B | Cross-org, shop, project, workspace, campaign boundary |
| Local/container user | OS, service, and runtime privilege boundary |

Capture available menus, route access, API responses, GraphQL fields, role IDs, group IDs, tenant IDs, workflow states, and side effects for each state.

## 2. Object, tenant, and workflow inventory

Inventory protected resources:

- Organizations, shops, stores, partners, workspaces, teams, programs, repositories, reports, tickets, tax documents, campaigns, ads, jobs, referrals, files, uploads, videos, admin sessions, and private metadata.
- Workflow states: unverified, invited, pending, approved, active, inactive, paid, unpaid, reviewed, deleted, archived, hidden, disabled, and impersonated.
- Privileged actions: invite, approve, verify, publish, activate, delete, generate session, impersonate, create admin, change status, copy file, export, view private metadata, access admin panel, upload executable content, and run service commands.

Prioritize actions with durable privilege, organization control, private data at scale, approval bypass, cross-tenant impact, or admin-side execution.

## 3. Email verification, SSO, and invite checks

Review:

- Email confirmation links, pending email changes, old verification links, unverified accounts, and ability to replace email before verification.
- Domain-based trust: services that treat `@company.com` or verified-email claims as authorization.
- OAuth/OIDC email verification claims and downstream apps that merge accounts by email.
- SAML signup restrictions, domain enforcement, trailing/control characters, Unicode, case normalization, and whitespace.
- Invite acceptance flows, collaborator conversion, partner/store join flows, org/workspace joins, duplicate invites, and existing-account linking.
- SSO/JIT/SCIM provisioning that creates or claims users across tenants.

Ask whether the system verifies ownership of the identity before granting tenant, store, partner, internal-service, or admin access.

## 4. Role and permission escalation checks

Review:

- Hidden pages and APIs for group management, user management, admin settings, referrals, billing, and program configuration.
- Permission IDs, role names, group membership, admin flags, feature flags, and generated session payloads.
- Low-role ability to assign permissions, create users, create hidden admins, invite admins, remove owners, or approve admin requests.
- Impersonation flows where admin sessions become visible or recoverable by the impersonated user.
- UI permission mismatch: menu hidden, route/API still reachable.
- Role duplication and same-email duplicate members with different permissions.

Confirm by checking durable permission state and whether future privileged actions succeed from a clean low-role session.

## 5. GraphQL and API authorization checks

Inspect:

- Resolver-specific authorization on nested fields and fragments.
- Admin operation names, generated session payloads, private metadata fields, report/retest/source fields, and team/org objects.
- REST/GraphQL mismatch for the same object or action.
- Direct object access through node IDs, global IDs, slugs, usernames, deleted object IDs, or stale references.
- API tokens or integration JWTs that expose more than their user's role.
- Mobile, internal, legacy, and undocumented APIs that skip permission checks.

GraphQL is especially likely to leak private metadata through low-risk-looking public profile, team, organization, repository, or report objects.

## 6. Business workflow bypass checks

Review client-supplied or API-visible workflow fields:

- `approved`, `admin_approval`, `effective_status`, `active`, `published`, `reviewed`, `payment_verified`, `verified`, `hidden`, `role`, `owner`, `tenant`, and `status`.
- Ad/job/campaign approval, payment-required activation, bounty/referral creation, account deletion, store publishing, partner approval, admin request approval, and moderation state.
- Whether a later async job, email, notification, billing process, or public listing honors the tampered state.
- Whether changing a state produces durable business impact even if UI later hides it.

Treat "pending but actionable" and "approved by client field" as high-value patterns.

## 7. Admin, debug, and infrastructure surface checks

Review exposed or weakly protected:

- Admin panels, WebCenter/Satellite, WordPress admin paths, Jira integrations, Phabricator, management consoles, Actuator, heapdump, memory dump, pprof, Docker Registry, CI/CD panels, and default-password admin management.
- Data exposed: credentials, secret keys, passwords, source code, admin accounts, tax documents, internal configs, private reports, and session payloads.
- Actions exposed: create admin, upload file, publish shell/backdoor, generate session, approve accounts, update merchant info, alter permissions, or run jobs.

Confirm whether the surface grants read-only sensitive data, write/admin actions, or a path to code execution.

## 8. Local, container, and root privilege escalation checks

Review:

- Trusted `$PATH`, helper binaries, setuid files, root-owned hooks, service restarts, package install hooks, writable directories, command execution APIs, and localhost-only privileged services.
- Container build systems, worker containers, package post-install scripts, image registries, migration hooks, Nomad templates, audit-forward hooks, and update-check scripts.
- Whether a low-privilege user can influence a command, environment variable, file path, package, template, or hook executed by a higher-privilege process.
- Whether SSRF or local access can reach a privileged localhost API that was assumed unreachable remotely.

Focus on privilege boundary crossing: user-to-SYSTEM/root, container-to-host-like control, editor-to-root SSH, admin-to-RCE, or service-user-to-secret access.

## 9. Confirmation rules

Strong evidence includes:

- Low-role user gains a higher role, hidden admin, generated admin session, or lasting permission change.
- Unverified or attacker-controlled email/domain obtains access to SSO, partner, store, org, or internal service.
- Low-role user approves, publishes, activates, or bypasses payment/review/moderation controls.
- Cross-tenant or private data is returned from an unauthorized tenant, org, repository, report, campaign, or deleted project.
- Integration token/JWT or GraphQL payload grants access beyond the user's permission.
- Exposed admin/debug surface reveals secrets or performs privileged actions.
- Local/container attack crosses into higher OS, service, or infrastructure privilege.

Rule out false positives:

- The role or workflow change appears in the client but does not persist server-side.
- The object is intentionally visible, inherited, public, shared, or user-owned.
- The endpoint accepts unauthorized fields but ignores them downstream.
- A chain requires manual action by a high-privilege user outside the product flow.
- Non-production data has no credential, production linkage, or operational impact.
- Local privilege issue does not cross a meaningful user, service, container, or host boundary.

## 10. Impact ranking

Rank by privilege gained, boundary crossed, durability, data sensitivity, scale, and prerequisites:

- Critical: full owner/admin takeover, SSO/org takeover, arbitrary verified email causing account takeover, production admin panel access, cross-tenant data at scale, generated admin sessions, local/container-to-root, or privilege escalation to RCE.
- High: member-to-admin, sensitive private data access, hidden admin persistence, approval/payment workflow bypass with public impact, OAuth/SAML authorization-code theft, integration JWT leak, or admin-side XSS with privileged data.
- Medium: limited role escalation, private metadata leak, workflow bypass with reversible impact, non-production admin data with secrets absent, or local service privilege increase with constraints.
- Low: low-sensitivity metadata, UI-only permission mismatch, self-owned object changes, or weak workflow inconsistency with no durable effect.

## 11. Developer remediation checklist

- Enforce authorization server-side for every route, API, GraphQL resolver, background job, admin panel, and generated session path.
- Recompute role, tenant, owner, verification, payment, approval, and workflow state server-side.
- Treat email verification, SSO domain, OAuth claims, SAML attributes, and invite acceptance as security boundaries with explicit ownership proof.
- Prevent low-role users from creating, hiding, duplicating, or modifying admin roles and permission groups.
- Validate workflow transitions with policy checks; never trust client-supplied status, approval, or role fields.
- Apply least privilege to integration JWTs, API tokens, generated sessions, and service accounts.
- Protect admin/debug/infrastructure surfaces with strong auth, network controls, secret hygiene, and disabled production debug endpoints.
- Add resolver-level authorization tests for GraphQL nested fields and admin operation names.
- Harden local/container privilege boundaries: sanitize environment and PATH, avoid privileged hooks on writable inputs, isolate containers, and restrict localhost privileged APIs.
- Add regression tests for role matrix, tenant matrix, stale/deleted object access, unverified email, invite acceptance, approval workflows, and admin-side rendering.
