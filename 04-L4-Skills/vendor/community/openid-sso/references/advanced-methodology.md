# OpenID and SSO Methodology

Use this reference to test federated identity trust.

## 1. Trust model

Map IdP, SP/RP, tenant, domain, user matching, role mapping, callback, ACS, metadata, and provisioning authority.

## 2. Assertion checks

Validate signature, issuer, audience, recipient, ACS, expiry, nonce, subject, NameID, email verification, and RelayState binding.

## 3. Provisioning checks

Review JIT, SCIM, invite acceptance, domain verification, deprovisioning, duplicate users, and existing-account matching.

## 4. Bypass checks

Test local fallback, XMLRPC, client-generated JWTs, unsigned tokens, trailing chars, Unicode, old metadata, and IdP/SP initiated differences.

## 5. Remediation checklist

- Validate assertions and ID tokens strictly.
- Bind RelayState and nonce to sessions.
- Treat email domain as sensitive authorization.
- Scope SCIM/JIT to verified tenants.
- Disable unintended local fallback auth.
