# Account Takeover Methodology

Use this reference to plan a thorough ATO assessment. The goal is to identify whether an account-control flow lets one identity gain, keep, or restore control over another account, session, credential, recovery factor, or linked identity.

## Contents

- Identity and asset matrix
- Flow inventory
- Token and binding analysis
- Test matrix
- Provider-specific checks
- Cache, proxy, and request-smuggling checks
- Mobile and desktop app handoff checks
- Confirmation rules
- Impact ranking
- Developer remediation checklist

## 1. Identity and asset matrix

Track identities and states before testing:

| Actor or state | Purpose | Examples |
| --- | --- | --- |
| A | Attacker-controlled account | Normal user, low-privilege member, attacker IdP account |
| B | Victim-controlled account | Separate email/phone, separate tenant, separate social login |
| Fresh browser | Clean-session control | No cookies, no local storage, no cached app state |
| Mobile app | Native auth path | Deeplinks, intents, app links, embedded WebView |
| SSO user | Enterprise path | SAML/OIDC user, SCIM-provisioned user, JIT user |
| Unverified state | Recovery edge case | Pending email, pending phone, pending invite, abandoned address |
| Changed state | Invalidity check | Password changed, email changed, factor changed, session revoked |

Track assets by owner and lifecycle: email, phone, username, user ID, tenant ID, session cookie, JWT, refresh token, remember-me token, CSRF token, OAuth state, nonce, auth code, PKCE verifier, reset token, OTP, magic link, invite link, device ID, API key, linked account ID, SAML NameID, SCIM external ID, and recovery factor.

## 2. Flow inventory

For every authentication or recovery flow, record:

| Field | What to capture |
| --- | --- |
| Entry point | Login, signup, reset, OAuth callback, SSO, mobile deeplink |
| Identity input | Email, phone, username, user ID, account ID, tenant |
| Secret or token | Session, JWT, reset token, OTP, auth code, magic link |
| Binding | Session, browser, device, tenant, user, client, redirect URI |
| Trust decision | What proves the user owns this account or recovery factor |
| Invalidation | What kills the token or session |
| Side effect | Password changed, email changed, factor added, account linked |

Prioritize flows that create or replace trust: password reset, email change, phone change, 2FA setup/reset, passwordless login, magic links, account linking, SSO join, SCIM provisioning, OAuth callback, and invite acceptance.

## 3. Token and binding analysis

Ask these questions for each token or secret:

- Who created it, who can receive it, and where can it leak?
- Is it bound to a user, session, tenant, browser, device, client, redirect URI, issuer, audience, or nonce?
- Is it single-use, time-limited, revocable, and invalidated by resend?
- Does changing password, email, phone, or 2FA invalidate old sessions and links?
- Is it stored in URLs, fragments, referers, logs, caches, HTML, local storage, or mobile intents?
- Can it be replayed from another browser, device, IP, app, tenant, or client?
- Does the server recompute ownership, or trust client-provided identity fields?

## 4. Test matrix

Run the matrix across high-impact flows:

| Test | Example |
| --- | --- |
| Recovery swap | Start reset for A and B, then swap token, email, phone, user ID, or callback fields |
| Stale recovery | Use old reset, email-change, phone-change, or magic-link tokens after a newer change |
| Session persistence | Check whether sessions survive password reset, email change, factor reset, or logout |
| Linked identity takeover | Attach A's social account, IdP account, or SSO identity to B |
| Pre-binding | Create or link an identity before B signs up or verifies an account |
| CSRF identity change | Trigger email, password, factor, linked-account, or security-question changes cross-site |
| OAuth callback abuse | Alter redirect, state, nonce, host, fragment, app scheme, client, or tenant |
| SSO/SCIM claim | Provision, update, deprovision, or reassign an existing user through enterprise flows |
| Cache/proxy leak | Cache or poison authenticated pages, token pages, or CSRF-bearing pages |
| Mobile handoff | Capture, inject, or replay auth results through deeplinks, intents, or WebViews |
| IDOR-to-ATO | Change member ID, email ID, profile ID, token ID, invite ID, or user record |

## 5. Provider-specific checks

OAuth/OIDC:

- Validate exact `redirect_uri` matching and reject open-redirect chains.
- Bind `state` and `nonce` to the initiating browser session.
- Verify `aud`, `iss`, `client_id`, token signature, token expiry, and user identity server-side.
- Treat email as verified only when the provider explicitly marks it verified.
- Prevent account linking unless the current user intentionally confirms the link.
- Avoid leaking codes or tokens through URLs, logs, referers, fragments handled by third-party scripts, or cross-origin redirects.

SAML/SSO:

- Bind RelayState to the intended tenant, session, and destination.
- Validate signatures, audience, recipient, ACS URL, issuer, NameID, and assertion lifetime.
- Avoid matching users solely by mutable email across untrusted tenants.
- Handle domain verification, deprovisioning, and JIT provisioning without letting an org claim existing unrelated users.

SCIM:

- Treat SCIM as account lifecycle authority only for verified domains and intended tenants.
- Prevent cross-tenant updates by external ID, email, username, or directory ID.
- Review create-vs-update behavior for existing users.
- Confirm deprovision/reprovision cannot reassign control or bypass a user's existing auth factors.

Passwordless and magic links:

- Bind links to the requested account, session, and purpose.
- Invalidate old links after resend, email change, password change, factor change, and successful use.
- Keep links out of third-party redirects, previews, logs, analytics, and referers.

## 6. Cache, proxy, and request-smuggling checks

Review edge behavior when auth material appears in responses:

- Missing or weak `Cache-Control` on authenticated pages.
- Missing `Vary: Cookie` or cache key confusion across users.
- Session cookies, CSRF tokens, magic links, or auth URLs in cacheable HTML or JavaScript.
- Host header trust in password reset links, OAuth callbacks, and absolute URLs.
- Reverse proxy normalization differences around path, host, headers, and duplicate cookies.
- Request smuggling or desync that can make another user's response include attacker-controlled content or leak cookies.
- Cache poisoning that stores XSS or redirects on authenticated paths.

## 7. Mobile and desktop app handoff checks

Review native auth edges:

- Custom URL schemes that any app can claim.
- App links/universal links that are not strongly associated with the right app.
- Intent redirects that forward auth codes, tokens, files, or WebView URLs.
- Embedded WebViews that expose cookies or tokens to JavaScript bridges.
- PKCE flows where the verifier is predictable, leaked, or not checked.
- Hardcoded client secrets, provider endpoints, feature flags, or recovery APIs in app bundles.
- Browser-to-app and app-to-browser transitions that lose state, nonce, tenant, or session binding.

## 8. Confirmation rules

Strong ATO evidence shows control, not just reachability:

- A can authenticate as B in a clean browser or device.
- A changes B's password, email, phone, 2FA, recovery code, or security questions.
- A binds A's OAuth/SAML/social identity to B.
- A obtains and reuses B's session, refresh token, API token, reset token, auth URL, or magic link.
- A keeps access after B logs out, changes password, or rotates factors.
- A crosses tenant or enterprise boundaries through SSO, SCIM, invites, or provisioning.

Rule out false positives:

- The flow only controls an account A created.
- The account is unverified and cannot access sensitive data or actions.
- The victim must manually copy a secret outside the app flow.
- State, nonce, token audience, client, tenant, and redirect URI are enforced correctly.
- Tokens expire quickly, are single-use, and invalidate on account-control changes.
- Sessions rotate and old sessions die on sensitive changes.

## 9. Impact ranking

Rank risk by control depth, victim interaction, scale, and prerequisites:

- Critical: no-interaction or one-click takeover, mass account takeover, staff/admin takeover, password reset without victim action, session theft at scale, SSO/SCIM takeover of existing users, or auth-token theft across many tenants.
- High: durable takeover of one account, recovery-channel replacement, linked-account binding, 2FA reset, API token disclosure, or OAuth/OIDC/SAML flow takeover with plausible interaction.
- Medium: partial account control, unverified-account takeover with meaningful actions, session persistence after sensitive changes, or control requiring rare victim state.
- Low: weak pre-account takeover without sensitive access, self-account-only issues, or findings that require unrealistic external secret disclosure.

## 10. Developer remediation checklist

- Bind every auth token, reset token, magic link, OAuth state, nonce, and auth code to the intended user, session, client, tenant, purpose, and redirect destination.
- Invalidate sensitive tokens and sessions after password, email, phone, 2FA, linked-account, SSO, and recovery-factor changes.
- Enforce exact redirect URI matching and reject open-redirect chains in auth callbacks.
- Verify OAuth/OIDC token signature, issuer, audience, expiry, nonce, email verification, and client identity server-side.
- Require intentional user confirmation for linked accounts, recovery-factor changes, and identity-provider binding.
- Protect identity-changing endpoints with robust CSRF defenses and SameSite-aware cookie design.
- Set defensive cache headers on authenticated and token-bearing pages; include `Vary: Cookie` where needed.
- Harden cookie scope, parsing, rotation, HttpOnly, Secure, and SameSite behavior.
- Treat SSO/SCIM provisioning as tenant-scoped lifecycle control, not as generic email ownership proof.
- Test mobile deeplinks, app links, intents, WebViews, and PKCE with regression cases.
