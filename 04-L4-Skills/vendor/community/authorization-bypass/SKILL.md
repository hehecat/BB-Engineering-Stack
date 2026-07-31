---
name: authorization-bypass
description: Advanced authorization bypass and privilege escalation testing methodology for bug bounty and application security work. Use when testing or reviewing role escalation, admin escalation, tenant or organization boundary bypass, email verification bypass, invitation or SSO join flaws, OAuth/SAML authorization misuse, GraphQL or API authorization leaks, hidden admin accounts, approval workflow bypass, business-rule authorization gaps, unauthorized private data access, exposed admin panels, local-to-root or container privilege escalation, and workflows where a lower-privilege identity can read, act, approve, impersonate, or administer beyond its intended permissions.
---

# Authorization Bypass Testing

## Core Posture

Treat authorization bugs as failures to enforce who may perform an action on which object, tenant, role, workflow state, or trust domain. Test the server-side decision, not the visibility of UI controls.

Use public case lessons as prioritization signals, not as a fixed recipe. Choose inspection methods from the user's artifacts and target type. Do not narrow the skill to IDOR alone; include role escalation, workflow bypass, SSO/domain trust, GraphQL, admin panels, local/container privilege boundaries, and cross-tenant systems.

## Priority Patterns

Prioritize flows where one identity can become more trusted or act across a boundary:

- Email verification and SSO trust: arbitrary email confirmation, partner email confirmation bypass, OAuth grants with unverified email, SAML signup domain bypass, and services that trust email domain as authorization.
- Invitation and organization joins: store/shop/partner invites, workspace joins, collaborator conversion, hidden admin accounts, duplicate role invitations, and join flows that skip verification.
- Role and permission escalation: member-to-admin, program-only-to-admin, staff-without-permission to admin GraphQL payload, owner/admin impersonation, and permission screens that do not match backend access.
- Business workflow bypass: admin approval, payment-detail requirement, ad/job approval, effective status toggles, referral creation, store publishing, account deletion, and moderation workflow state changes.
- Cross-tenant and private data access: private repositories, private reports, undisclosed metadata, tax documents, support tickets, private videos, private program policy, tenant campaigns, and deleted-project data.
- OAuth/SAML/Jira/SSO authorization: redirect URI authorization-code theft, Jira OAuth controller SSRF, leaked integration JWTs, SSO org claim, domain enforcement bypass, and OAuth-bypassed admin panels.
- GraphQL and API authorization: nested field leaks, object type fields exposed to low roles, undocumented admin operations, resolver-specific gaps, and REST/GraphQL permission drift.
- Exposed high-privilege surfaces: admin panels, Oracle WebCenter, WordPress admin hardening bypass, Spring Actuator heap dumps, memory dumps, management consoles, and default admin credentials.
- Local, container, and root escalation: trusted `$PATH`, helper services, root-owned hooks, worker containers, localhost privileged APIs, Apache local root, and service-to-root transitions.
- Admin-side injection chains: blind XSS in admin dashboards, stored XSS through custom IDs/uploads, SQLi in admin panels, and file upload paths that become privileged code execution.

## Assessment Loop

1. Map principals: anonymous user, normal user, external user, invited user, member, staff, viewer, program-only role, admin, owner, service account, SSO user, tenant admin, container user, and local OS user.
2. Map protected decisions: join, invite, approve, verify, impersonate, publish, delete, export, view private data, generate session, create admin, change status, create referral, copy file, or run privileged code.
3. Build state pairs: verified vs unverified email, invited vs accepted, active vs deleted project, paid vs unpaid, pending vs approved, owner vs staff, admin vs limited role, tenant A vs tenant B.
4. Capture the expected low-role and high-role flows, then compare route, API, GraphQL, mobile, legacy, and direct object paths for the same action.
5. Test boundary swaps: low role against high-role endpoint, tenant A against tenant B object, unverified identity against verified-only flow, pending object against approved-only flow, stale/deleted object against active data.
6. Test workflow-field trust: role, status, approval, owner, tenant, email verification, invite state, payment status, hidden flag, admin flag, generated session, and impersonation state.
7. Confirm whether the lower-privilege identity can read, mutate, approve, impersonate, persist, or escalate beyond its intended boundary.

## High-Value Cues

| Family | Look for | Ask |
| --- | --- | --- |
| Email/domain trust | verified email, domain allowlist, SSO signup, partner email, OAuth email | Can unverified or attacker-controlled email unlock another trust domain? |
| Invites/org joins | invite ID, collaborator, workspace join, partner store, organization member | Can A join, claim, or convert into a privileged account without the intended approval? |
| Roles/permissions | role ID, group ID, admin flag, permission list, hidden menus, GraphQL payload | Does the backend enforce the role or only hide controls? |
| Workflow approval | `approved`, `effective_status`, payment, moderation, job/ad status | Can A set the final state directly or skip the review requirement? |
| Tenant/object access | org, shop, project, team, report, repo, campaign, deleted project | Can A access B's data through alternate routes, stale objects, or nested fields? |
| Impersonation/session | admin impersonates user, generated session, staff token, integration JWT | Can a low-role user capture, reuse, or generate a higher-privilege session? |
| GraphQL/API | nested fields, admin operation names, private metadata, undocumented mutation | Are resolver permissions stricter than UI/API route permissions? |
| Admin surfaces | admin panel, default password, actuator, heapdump, memory dump, WebCenter | Does public or low-role access reveal credentials, users, configs, or admin actions? |
| Local/container priv-esc | helper, `$PATH`, setuid, root hook, worker container, localhost API | Can a lower local/container user trigger privileged code or file access? |
| Admin-side injection | stored XSS, file upload, SQLi, custom UUID, admin-rendered fields | Can low-role input execute or leak data in a privileged admin context? |

## Variant Playbook

- Replay high-role requests as low-role users and compare response, side effect, audit trail, and later UI state.
- Toggle role, approval, verification, owner, tenant, status, hidden, payment, and admin fields in body, GraphQL variables, query strings, and multipart metadata.
- Try direct routes to hidden pages, admin endpoints, GraphQL operations, mobile APIs, internal APIs, legacy routes, and generated-session endpoints.
- Test stale states: deleted project, removed member, expired invite, old verification link, unverified email, disabled tenant, archived campaign, and pending approval.
- Compare SSO/OAuth/SAML user matching across email, domain, NameID, tenant, RelayState, callback, invite, and organization membership.
- Check whether low-role users can create, duplicate, hide, approve, or remove admin accounts and roles.
- Inspect nested GraphQL fields for private metadata returned by public profile, team, report, project, repository, or organization objects.
- Review approval workflows for client-supplied state transitions: pending-to-approved, inactive-to-active, unpaid-to-paid, unreviewed-to-published.
- Test infrastructure privilege boundaries: local user to SYSTEM/root, container user to host-like privilege, admin panel to shell, exposed debug endpoint to secrets.
- Chain carefully within the model: access-control gap plus XSS, SSRF plus localhost privileged API, leaked JWT plus integration API, admin panel plus upload, role bypass plus RCE.

## Confirmation Discipline

An authorization finding needs boundary-crossing evidence, not just an unexpected page load.

Strong evidence includes:

- A lower-privilege user gains admin/owner/staff capability or durable role state.
- A user joins, claims, verifies, or controls an organization, store, tenant, or partner account they should not control.
- A low-role identity approves, publishes, activates, deletes, or changes a workflow state reserved for admins or payment/review systems.
- A user reads private tenant, repository, report, campaign, ticket, document, tax, metadata, or video data outside their boundary.
- A leaked or generated session/JWT lets an unauthorized user act as a higher role.
- A local/container/process user crosses into SYSTEM/root/admin or privileged service execution.
- A privileged admin-side context executes low-role input or leaks privileged data.

Rule out weak findings:

- The UI reveals a button but the backend rejects the action.
- The data is intentionally public, shared, inherited, or visible through legitimate membership.
- The state change is accepted but ignored by downstream workflow.
- The role change affects only an attacker-owned test object without a path to broader privilege.
- The endpoint is non-production with no sensitive data, credential, privilege, or production linkage.
- The chain depends on a higher-privilege user voluntarily granting permission outside the application flow.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper role matrix, workflow-state matrix, SSO/OAuth/SAML authorization review, GraphQL/API authorization review, admin surface review, local/container privilege escalation review, confirmation checklist, impact ranking, or remediation checklist.
