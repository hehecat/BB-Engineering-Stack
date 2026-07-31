# Authentication Hacking Methodology

Use this reference to plan a thorough authentication security assessment. The goal is to verify whether each auth boundary is enforced server-side and whether identity, session, factor, token, redirect, and device state remain bound through the whole flow.

## Contents

- Auth surface inventory
- Identity and state matrix
- Credential and token inventory
- Bypass test matrix
- Redirect and middleware checks
- OTP, passwordless, and MFA checks
- SSO, SAML, OAuth, and JWT checks
- Session and cookie checks
- Brute-force, throttling, and enumeration checks
- Exposed infrastructure and pre-auth service checks
- Confirmation rules
- Impact ranking
- Developer remediation checklist

## 1. Auth surface inventory

Collect auth surfaces from:

- Browser routes: login, logout, signup, reset, account settings, admin, reauth prompts, MFA setup, recovery, and invite acceptance.
- API routes: auth endpoints, mobile endpoints, XMLRPC, WebDAV, legacy APIs, GraphQL, passwordless APIs, OTP APIs, and account/security settings APIs.
- Federated auth: SAML ACS, OAuth/OIDC callbacks, social login, SSO portals, global site selectors, IdP-initiated login, and local fallback auth.
- Infrastructure services: VPNs, Jenkins, Docker Registry, Spring Actuator, monitoring, Icinga, KVM, CCTV backups, Jenkins test instances, middleware portals, and appliance consoles.
- Client artifacts: JavaScript bundles, mobile/desktop app storage, CI logs, Docker images, config files, old commits, public backups, and downloadable app data.

Record host, path, method, client type, credential type, session issuance point, redirect behavior, middleware check, backend check, state change, and protected resource.

## 2. Identity and state matrix

Test with distinct identities and auth states:

| State | Purpose |
| --- | --- |
| Anonymous | Missing-auth and redirect-gate boundary |
| Attacker A | Control account and baseline flow |
| Victim B | Identity-swap and account-control boundary |
| Unregistered | Signup/registration bypass checks |
| Unverified | Email/phone verification bypass checks |
| 2FA enabled | MFA enforcement and disable checks |
| 2FA absent | 2FA-linking and enrollment takeover checks |
| Logged out | Session invalidation checks |
| Expired session | Timeout and stale-token checks |
| Banned/removed/deleted | Lifecycle revocation checks |
| SSO user | Federated identity and fallback auth checks |
| Mobile/desktop session | Client parity and local storage checks |

Track whether each state can login, refresh tokens, call APIs, access protected pages, change security settings, or reach infrastructure panels.

## 3. Credential and token inventory

Track:

- Password, OTP, backup code, magic link, reset token, email-change token, phone-change token, CSRF token, session cookie, refresh token, JWT, remember-me token, API token, bot key, client certificate, OAuth code, SAML assertion, RelayState, `state`, `nonce`, and device token.
- Issuer, receiver, storage location, owner, tenant, client, lifetime, revocation event, binding, scope, replay behavior, and invalidation rules.
- Leakage locations: URL, Referer, redirect, logs, CI, Docker image, mobile files, local storage, path traversal, exported project data, debug endpoint, and HTTP transport.

Ask whether the secret proves identity by itself or must be combined with session, device, tenant, client, callback, or fresh password proof.

## 4. Bypass test matrix

Run these checks across high-value auth surfaces:

| Test | Example |
| --- | --- |
| Direct access | Request protected/admin path without following login redirect |
| Redirect block | Stop 302/401/403 chain and request the protected resource directly |
| Response trust | Change client-visible auth result, then verify server-side follow-up |
| Identity swap | Use A session with B user ID, phone, email, tenant, or factor ID |
| State mismatch | Use stale, logged-out, expired, banned, or removed-user token |
| Reauth bypass | Change email, phone, password, 2FA, or recovery without fresh proof |
| OTP swap | Pair A session/token with B phone/user ID/code flow |
| MFA bypass | Disable, skip, relink, reuse, or enforce MFA inconsistently |
| Fallback bypass | Use XMLRPC, WebDAV, mobile, legacy, or local login beside SSO |
| Token leak | Reuse exposed token from logs, app storage, redirect, or traversal |
| Subdomain trust | Abuse taken-over trusted host, cookie scope, or redirect allowlist |
| Exposed panel | Access infrastructure service without auth and test read/write impact |

## 5. Redirect and middleware checks

Inspect:

- Whether protected resources enforce auth after redirects are blocked.
- Middleware route matching for `/admin`, encoded paths, trailing slashes, path traversal, alternate extensions, method override, and static file routes.
- Host header and reverse proxy behavior around login redirects and absolute URLs.
- Response codes vs backend state: a 302 or 403 may hide a body, and a 200 may only reflect client-side UI state.
- Client-side route guards in SPAs that hide APIs but do not protect backend routes.
- Login status endpoints that create sessions, bootstrap state, or expose protected user data.

Confirm by making a follow-up protected request using only server-issued credentials, not browser UI changes.

## 6. OTP, passwordless, and MFA checks

Review:

- OTP/session binding to user, phone, device, flow, and purpose.
- OTP leakage in responses, logs, SMS preview APIs, debug payloads, and client storage.
- OTP resend invalidation, attempt limits, code lifetime, reuse, and race behavior.
- Logout/login pairs where a user ID or session token can be swapped.
- Passwordless links bound to session, browser, tenant, and purpose.
- MFA enrollment, disable, recovery code, backup code, and enforcement policy across web/mobile/API.
- Fresh password requirements for disabling 2FA or changing email, phone, password, security questions, and recovery settings.

Check both "2FA already enabled" and "2FA not yet enabled" states; many bypasses live in enrollment, linking, or enforcement gaps.

## 7. SSO, SAML, OAuth, and JWT checks

Review:

- OAuth/OIDC: exact `redirect_uri`, `state`, `nonce`, `client_id`, audience, issuer, code exchange, PKCE, token expiry, email verification, and account linking.
- SAML: signature validation, assertion audience, recipient, ACS URL, NameID, RelayState, IdP-initiated login, assertion lifetime, and tenant binding.
- SSO plugins: local login fallback, XMLRPC fallback, default passwords, auto-provisioning, role assignment, and disabled normal-login routes.
- JWT: signature enforcement, algorithm confusion, unsigned tokens, expiry, issuer, audience, tenant, and user claim trust.
- Host/callback parsing: duplicate params, encoded values, fragment handling, client-side parser mismatch, and open redirects.
- Subdomain takeover: trusted callback domains, static hosts, cookie scope, OAuth redirect allowlists, and SSO assets.

Treat the federated provider and the relying party as two systems that must agree on identity, session, client, and tenant.

## 8. Session and cookie checks

Review:

- Session rotation after login, password reset, password change, email change, MFA change, logout, and privilege change.
- Cookie domain, path, Secure, HttpOnly, SameSite, expiry, duplicate cookie parsing, subdomain injection, and fixation.
- Token replay from another browser, IP, device, client, app, tenant, or after logout.
- Remember-me and desktop/mobile persistence after uninstall/reinstall, session timeout, password change, and factor change.
- Path traversal or local file exposure that reveals auth tokens.
- Auth token theft through open redirect, Referer, HTTP reset links, callback URL parameters, logs, or cache.

Confirm whether an old token can still perform privileged actions, not just whether it appears syntactically valid.

## 9. Brute-force, throttling, and enumeration checks

Review:

- Login, OTP, password reset, basic auth, WebDAV, API auth, recovery, username search, and MFA endpoints.
- Throttle dimensions: account, IP, session, device, username, password, endpoint, tenant, ASN, and client type.
- Lockout abuse where A can deny service to B by failing logins.
- Timing differences for valid vs invalid users, disabled users, SSO users, or 2FA users.
- Replay of captured login responses or bypass of `429 Too Many Requests`.
- Distributed attempt behavior across IPv6, headers such as `X-Forwarded-For`, mobile clients, and legacy endpoints.

Differentiate realistic credential attack, account lockout, and enumeration impact.

## 10. Exposed infrastructure and pre-auth service checks

Prioritize:

- VPN appliances, Jenkins, Docker Registry, Spring Actuator, Icinga, monitoring dashboards, admin panels, KVM/TinyPilot, CCTV backups, WebDAV, XMLRPC, and test/staging services.
- Pre-auth file read, config read, credential disclosure, image dump, backup download, job creation, plugin upload, debug endpoint, or command execution paths.
- Default credentials, missing auth, reverse proxy auth gaps, middleware bypass, client certificate mistakes, and network-only assumptions.
- Publicly reachable debug or admin paths that reveal sessions, tokens, environment variables, logs, configs, or internal service credentials.

Focus on whether unauthenticated or weakly authenticated access crosses from "view page" into sensitive data, credentials, write capability, or code execution.

## 11. Confirmation rules

Strong auth evidence includes:

- A valid server-issued session is obtained without the required credential, factor, or federated proof.
- A protected page, API, file, or admin function is reachable after bypassing the intended auth gate.
- A sensitive setting changes without fresh password or MFA proof.
- A stale, leaked, malformed, empty, or client-controlled token is accepted by privileged server-side actions.
- A federated callback, SAML assertion, OAuth code, JWT, or local fallback logs in the wrong user or wrong role.
- A pre-auth service exposes credentials, config, backups, job control, image access, or RCE path.

Rule out false positives:

- Only client-side UI says logged in and no server-side privileged action succeeds.
- The protected resource returns only intentionally public data.
- The bypass depends on an attacker-created account with no victim, role, or privilege crossing.
- Redirect blocking reveals a page shell but backend APIs remain protected.
- A leaked token is revoked, expired, scoped harmlessly, or rejected by sensitive actions.
- Rate-limit observations do not enable realistic guessing, enumeration, lockout, or replay.

## 12. Impact ranking

Rank risk by authentication boundary crossed, account control, privilege, data sensitivity, scale, and prerequisites:

- Critical: pre-auth RCE, admin auth bypass, mass account login, SSO/SAML/OAuth takeover, valid production auth token leak, exposed infrastructure with secrets/write access, or bypass leading to account takeover.
- High: protected data access without auth, password/2FA/email change without fresh proof, token replay after logout/change, 2FA bypass, subdomain takeover into auth, or strong credential brute force at scale.
- Medium: partial auth bypass, account lockout, user enumeration with reliable signal, missing auth on limited data, stale session with constrained actions, or low-privilege infrastructure read access.
- Low: weak auth indicators without sensitive access, self-account-only behavior, public data behind unnecessary login, or rate-limit behavior with little practical effect.

## 13. Developer remediation checklist

- Enforce authentication server-side at every protected route, API, static/resource path, and backend action.
- Avoid relying on redirects, SPA route guards, client responses, or hidden UI as authentication controls.
- Bind OTPs, tokens, sessions, SAML assertions, OAuth codes, JWTs, and bot keys to user, device/session, client, tenant, purpose, and lifetime.
- Require fresh password or MFA proof before changing password, email, phone, 2FA, recovery settings, or linked identities.
- Rotate and invalidate sessions after login, logout, password reset, password change, email/phone change, MFA change, privilege change, ban, and account deletion.
- Validate OAuth/OIDC/SAML/JWT signatures, issuer, audience, recipient, redirect/callback, `state`, `nonce`, expiry, and tenant.
- Disable or protect XMLRPC, WebDAV, local login fallback, debug panels, appliance consoles, and infrastructure APIs.
- Scope cookies narrowly and set Secure, HttpOnly, SameSite, correct domain/path, and robust duplicate-cookie parsing.
- Protect login, OTP, basic auth, WebDAV, recovery, and MFA with account-aware throttling, anti-automation, and lockout-abuse controls.
- Remove secrets from logs, app bundles, Docker images, public repos, callbacks, reset links, HTTP transport, and downloadable files.
