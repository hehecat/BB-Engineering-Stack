---
name: account-takeover
description: Advanced account takeover (ATO) testing methodology for bug bounty and application security work. Use when testing or reviewing login, password reset, email or phone change, OAuth/OIDC/SAML/social login, magic links, session cookies, JWTs, remember-me tokens, CSRF on identity-changing actions, linked accounts, SSO/SCIM provisioning, mobile deeplinks or intents, web cache issues, request smuggling chains, exposed admin/debug endpoints, and any workflow where a flaw may let one user obtain another user's session, reset credentials, bind an attacker-controlled identity, or assume account control.
---

# Account Takeover Testing

## Core Posture

Treat ATO as a control-plane failure: an attacker gains durable control of an account, authentication credential, recovery channel, linked identity, or active session. Do not stop at "login worked"; identify which trust boundary failed and whether control persists after logout, password change, email change, 2FA change, session rotation, or account recovery.

Use public case lessons as prioritization signals, not as a fixed recipe. Choose inspection methods from the user's artifacts and target type. Do not narrow the skill to one artifact type, one login provider, or one exploit chain.

## Priority Patterns

Prioritize workflows where account identity, credentials, recovery, sessions, or federated trust are changed or consumed:

- Session and token possession: leaked cookies, auth tokens in URLs, cacheable authenticated pages, token reuse, weak session rotation, cookie parsing quirks, cookie domain/path mistakes, and session fixation.
- Password reset and recovery: reset token generation, token reuse, token invalidation, race conditions, email/phone ownership checks, magic links, passwordless signup, OTP/SMS flows, and recovery-channel changes.
- OAuth/OIDC/social login: redirect URI validation, state and nonce binding, callback host handling, token audience/client validation, linked account CSRF, missing email verification, Google/Apple/OneTap flows, and mobile OAuth handoff.
- CSRF and click-driven identity changes: email change, password change, security questions, 2FA setup/reset, linked accounts, API keys, invite acceptance, and account deletion or restoration.
- XSS-to-ATO chains: cookie/token theft, login keylogging, stored XSS in trusted subdomains, CSP bypasses, token-bearing postMessage flows, and XSS on OAuth or payment/auth surfaces.
- Request smuggling, cache deception, and cache poisoning: stealing session cookies, caching private pages, poisoning authenticated responses, leaking CSRF tokens, and desynchronizing front-end/back-end auth assumptions.
- SSO, SAML, SCIM, and enterprise provisioning: verified domains, Just-In-Time provisioning, user matching, RelayState, SAML response binding, org join flows, SCIM user updates, and SSO lockout-to-takeover pivots.
- Mobile and desktop app flows: deeplinks, intent redirects, WebViews, universal/app links, custom schemes, embedded client secrets, authorization code with PKCE mistakes, and cross-app token delivery.
- Exposed control surfaces: debug/admin endpoints, Spring Actuator, cloud identity APIs, SSRF into metadata or internal auth services, reverse proxy misconfiguration, host header trust, and environment leaks.
- IDOR-to-ATO: editable user records, member IDs, email/phone fields, API tokens, team permissions, invitation confirmation links, and cross-tenant password reset or provisioning paths.

## Assessment Loop

1. Map identity assets: account identifiers, emails, phone numbers, usernames, user IDs, tenant IDs, session cookies, JWTs, refresh tokens, reset tokens, OTPs, API keys, linked identities, device IDs, and recovery factors.
2. Build state pairs: attacker account, victim account, unverified email, verified email, changed email, logged-out session, expired token, 2FA-enabled account, SSO account, mobile app session, and linked social account.
3. Capture complete flows: login, logout, signup, password reset, passwordless signup, email/phone change, 2FA setup/reset, OAuth callback, account linking, invite acceptance, SCIM provisioning, SSO join, magic link, and session refresh.
4. Track every secret and binding: where it is issued, where it is stored, what it is bound to, how long it lives, whether it is single-use, and what invalidates it.
5. Test account-boundary swaps: attacker session with victim identifier, attacker recovery flow with victim email/phone, attacker OAuth state with victim callback, attacker token on victim endpoint, and stale token after account changes.
6. Test cross-surface delivery: browser to mobile, mobile to browser, WebView to native app, subdomain to parent domain, OAuth provider to relying party, SSO IdP to service provider, and proxy/cache edge to origin.
7. Confirm durable control: session access, credential reset, recovery-channel ownership, linked identity takeover, 2FA factor replacement, API token access, or persistent ability to re-enter the account.

## High-Value Cues

| Family | Look for | Ask |
| --- | --- | --- |
| Password reset | reset token, code, email, phone, user ID, callback URL, resend endpoint | Can A reset or consume B's recovery flow without B completing it? |
| Session/token | `Set-Cookie`, JWT, refresh token, remember-me, auth URL, CSRF token | Can A obtain, reuse, fix, cache, or keep B's authenticated state? |
| OAuth/OIDC | `redirect_uri`, `state`, `nonce`, `code`, `client_id`, `aud`, `iss`, callback host | Are callback, user identity, and token audience bound to the right session and client? |
| Linked accounts | Google/Apple/Facebook/GitHub link, unlink, merge, invite, account claim | Can A bind their identity provider to B's account or pre-bind B's email? |
| Email/phone change | pending email, old verification link, unverified state, abandoned address, OTP | Do stale links, unverified values, or recovery factors remain valid after changes? |
| CSRF | identity-changing POSTs, JSON APIs, weak Origin/Referer checks, SameSite gaps | Can a state-changing account-control request be triggered cross-site? |
| XSS chains | token-bearing page, auth subdomain, trusted redirect, postMessage, cookie reflection | Can script execution reach credentials, linked-account flows, or session-bearing actions? |
| Cache/proxy | private page cache headers, `Vary`, CDN key, host header, path confusion, smuggling | Can authenticated content or token material be served to the wrong user? |
| SSO/SCIM | domain verification, JIT provisioning, RelayState, NameID/email mapping, user import | Can enterprise identity matching create, claim, replace, or lock out existing users? |
| Mobile handoff | deeplinks, custom schemes, intents, WebViews, app links, PKCE verifier | Can another app or link capture or inject the auth result? |

## Variant Playbook

- Swap identifiers across flow stages: email, phone, username, user ID, tenant ID, invite ID, reset token, OAuth state, device ID, and linked-account ID.
- Replay old links and tokens after logout, password change, email change, 2FA change, resend, account deletion, account restoration, and session expiration.
- Race paired flows: attacker and victim password reset, two email changes, simultaneous OTP verification, magic-link resend, account linking, and SSO join.
- Mismatch trust data: attacker session with victim email, victim token with attacker callback, attacker OAuth state with victim browser, wrong `client_id`, wrong `aud`, wrong tenant, or altered Host header.
- Probe redirect and callback handling: exact match, scheme changes, subdomain tricks, path confusion, double encoding, fragment handling, open redirects, and mobile custom schemes.
- Check cookie and session semantics: rotation after login/reset, domain/path scope, HttpOnly/Secure/SameSite, duplicate cookie parsing, subdomain cookie injection, and remember-me invalidation.
- Review cache and proxy behavior: private data cached publicly, missing `Vary: Cookie`, cache key confusion, cacheable CSRF pages, proxy normalization differences, and smuggling-induced response mixups.
- Inspect mobile and client bundles for auth endpoints, deeplink routes, embedded client IDs, postMessage origins, feature flags, hidden recovery APIs, and provider configuration.
- Test enterprise flows: domain verification edge cases, SCIM update semantics, JIT account creation, deprovision/reprovision, IdP-initiated login, RelayState handling, and multi-tenant user matching.

## Confirmation Discipline

An ATO proof needs account-control evidence, not just a suspicious redirect or status code.

Strong evidence includes:

- A logs into or maintains a session as B.
- A resets B's password, replaces B's email/phone, or adds a recovery factor.
- A links an attacker-controlled identity provider to B.
- A obtains B's session cookie, auth token, reset token, magic link, API token, or authorization URL.
- A reaches sensitive account actions as B after logout, password reset, email change, or session rotation.
- A can reproduce control across another browser, device, or clean session.

Rule out weak findings:

- The flow only affects an attacker-created account with no victim claim path.
- The victim must voluntarily reveal a secret outside the application flow.
- The token is single-use and bound correctly to the victim session.
- The callback rejects mismatched state, nonce, audience, issuer, or client.
- The account remains unverified and cannot access meaningful data or privileged actions.
- The session dies after password reset, email change, logout, or factor change.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper identity matrix, auth-flow inventory, provider-specific checks, cache/proxy review, mobile handoff review, confirmation checklist, impact ranking, or remediation checklist.
