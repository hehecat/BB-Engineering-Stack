# OAuth Methodology

Use this reference to test OAuth/OIDC-style authorization flows.

## 1. Flow inventory

Record authorize URL, callback, token exchange, linking endpoint, session issuance, client ID, redirect URI, scope, state, nonce, and provider.

## 2. Redirect review

Test exact matching, open redirect chains, path traversal, encoding, fragments, wildcard hosts, IDN, userinfo, and mobile schemes.

## 3. Binding review

Bind state, nonce, code, token, client, redirect, user, tenant, and purpose. Swap between sessions and accounts.

## 4. Account linking

Test forced linking, unverified email, pre-binding, provider mismatch, and OAuth CSRF.

## 5. Remediation checklist

- Enforce exact redirect allowlists.
- Bind state/nonce to session.
- Verify token issuer/audience/expiry.
- Trust only verified email claims.
- Require explicit account-link confirmation.
