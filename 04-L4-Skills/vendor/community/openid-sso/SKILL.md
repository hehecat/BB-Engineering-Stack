---
name: openid-sso
description: Advanced OpenID, OIDC, SAML, and SSO security testing methodology for bug bounty and application security work. Use when testing or reviewing SSO login, SAML assertions, OpenID Connect ID tokens, SSO domain enforcement, JIT/SCIM provisioning, RelayState, signed assertions, JWT client-side generation, organization joins, enterprise identity matching, SSO token theft, SSO DoS, and workflows where federated identity grants account, tenant, or internal-service access.
---

# OpenID and SSO Testing

## Core Posture

Treat SSO as delegated authorization: the service must verify identity, domain, tenant, client, assertion, and session binding before granting access.

## Priority Patterns

- Email/domain verification bypass: arbitrary verified email, domain enforcement gaps, trailing/control characters, and unverified OAuth grants.
- SAML/OIDC validation gaps: weak signatures, audience, recipient, issuer, lifetime, RelayState, nonce, and client checks.
- JIT/SCIM provisioning: creating or claiming existing users, wrong tenant matching, and deprovisioning gaps.
- Token theft: SSO login token leaks, callback leaks, open redirect, and client-side JWT generation.
- Fallback auth: local login, XMLRPC, default password, and plugin bypass beside SSO.

## Assessment Loop

1. Map IdP, SP/RP, callback, ACS, metadata, user matching, tenant matching, and provisioning.
2. Track email, domain, NameID, subject, tenant, RelayState, client, audience, issuer, nonce, and assertion lifetime.
3. Test unverified, external, invited, existing, deprovisioned, and duplicate identities.
4. Compare IdP-initiated, SP-initiated, local fallback, API, and mobile flows.
5. Confirm unauthorized org/internal access, account claim, token theft, or SSO disruption.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Domain enforcement | Can formatting bypass protected domain signup? |
| Assertion validation | Are signature, audience, recipient, issuer, and time checked? |
| User matching | Can email/NameID claim an existing account? |
| RelayState | Can it move users into an attacker tenant or destination? |
| Fallback auth | Does local/XMLRPC login bypass SSO policy? |

## Variant Playbook

- Test case, Unicode, whitespace, trailing control chars, plus aliases, and domain normalization.
- Alter RelayState, ACS URL, audience, recipient, issuer, NameID, email, and group claims.
- Test unsigned/weak JWTs, client-generated JWTs, old metadata, and expired assertions.
- Compare JIT create vs update and SCIM create vs update behavior.
- Test deprovisioned users, removed tenants, duplicate invites, and local fallback routes.

## Confirmation Discipline

Strong evidence shows unauthorized org access, account claim, internal service access, token theft, or role escalation through federated trust. Rule out self-owned test-tenant behavior without cross-boundary impact.

## References

Read `references/advanced-methodology.md` only when the task needs deeper SAML/OIDC validation, domain enforcement, SCIM/JIT, fallback auth, confirmation, or remediation checks.
