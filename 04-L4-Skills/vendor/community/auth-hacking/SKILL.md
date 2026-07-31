---
name: auth-hacking
description: Advanced authentication security testing methodology for bug bounty and application security work. Use when testing or reviewing login, logout, registration, OTP/SMS, password reauthentication, password reset, session cookies, auth tokens, 2FA/MFA, SSO/SAML/OAuth/OIDC, subdomain-to-auth chains, redirect-based auth gates, middleware auth, response-manipulation auth bypass, brute-force throttling, exposed unauthenticated admin or infrastructure panels, pre-auth appliance flaws, client authentication, bot authentication, and any workflow where authentication can be bypassed, weakened, replayed, stolen, or desynchronized.
---

# Authentication Testing

## Core Posture

Treat authentication bugs as failures to prove identity, bind identity to a session, preserve authentication state, or require fresh proof before sensitive actions. Test the whole auth chain: entry point, credential, token, session, redirect, middleware, backend, client, and post-login state.

Use public case lessons as prioritization signals, not as a fixed recipe. Choose inspection methods from the user's artifacts and target type. Do not narrow the skill to web login forms; include APIs, mobile apps, SSO, VPNs, admin panels, appliances, CI logs, and infrastructure services.

## Priority Patterns

Prioritize auth flows that decide who the caller is or whether the caller is allowed past a gate:

- Pre-auth exposed infrastructure: VPNs, Jenkins, Docker Registry, Spring Actuator, monitoring panels, admin portals, CCTV backups, WebDAV, XMLRPC, TinyPilot/KVM, and appliance or middleware endpoints.
- Redirect-gate and middleware bypass: blocking redirects, changing 302/401/403 responses, direct access to post-auth paths, alternate routes, path traversal, method override, and middleware route mismatch.
- OTP and passwordless flows: OTP login/logout confusion, SMS session binding, OTP reuse, code leakage, missing phone verification, 2FA linking by user ID, and reset or recovery flows that trust client state.
- Password reauthentication bypass: changing email, phone, password, 2FA, recovery settings, or security-sensitive profile fields without fresh password proof.
- Session and token weakness: token theft, token replay, session persistence after logout/password change, auth cookies scoped too broadly, path traversal into token files, open redirects leaking tokens, and stale app tokens.
- SSO and federated auth: SAML assertion validation, OneLogin/WordPress plugin bypass, XMLRPC fallback auth, OAuth token impersonation, callback parsing, host trust, unsigned JWTs, SSH certificates, and global site selectors.
- Subdomain takeover to auth bypass: dangling auth-adjacent subdomains, cookie scope abuse, whitelisted redirect hosts, trusted static hosts, and SSO callback hosts.
- Brute force and throttling: IP-only rate limits, WebDAV/basic-auth gaps, replaying captured login responses, lockout abuse, username timing, and MFA attempt throttling.
- Client-side trust mistakes: response manipulation from `false` to `true`, client-side auth checks, hidden unauthenticated endpoints, and APIs that create valid sessions without credential proof.
- Authenticated-device and network assumptions: Bluetooth/device pairing, MITM-prone reset links, HTTP delivery of auth tokens, weak client authentication, bot keys, launcher persistence, and reinstall-keeps-session behavior.

## Assessment Loop

1. Map auth surfaces: login, logout, signup, reset, OTP, magic links, email/phone change, password reauth, 2FA setup/disable, SSO callback, OAuth callback, SAML ACS, mobile deeplink, admin path, API auth, and infrastructure panels.
2. Map auth artifacts: username, email, phone, user ID, session cookie, auth token, refresh token, OTP, reset token, CSRF token, SAML assertion, OAuth code, `state`, `nonce`, JWT, bot key, device ID, and client certificate.
3. Build identity states: anonymous, attacker A, victim B, unregistered user, unverified user, 2FA-enabled user, expired session, logged-out session, removed user, banned user, stale token, mobile session, and SSO user.
4. Capture normal flow boundaries: where identity is proven, where session is issued, where redirects occur, what middleware checks, what backend trusts, and what state changes require fresh proof.
5. Test bypass routes: direct URL access, alternate method, alternate host, mobile/API endpoint, legacy endpoint, XMLRPC/WebDAV path, blocked redirect, response tampering, stale token, and changed account state.
6. Test identity swaps: attacker session with victim ID, OTP flow with victim phone, 2FA setup with victim user ID, OAuth/SAML callback with attacker-controlled values, bot key with missing token part, and empty/null auth parameters.
7. Confirm whether the server, not the client, enforces authentication and whether control persists across clean browsers, logout, password change, session refresh, or reauthentication prompts.

## High-Value Cues

| Family | Look for | Ask |
| --- | --- | --- |
| Redirect gates | 302 to login, blocked redirect, direct `/admin`, response status flags | Does the backend enforce auth, or does the client/redirect hide an accessible resource? |
| OTP/passwordless | `user_id`, phone, session token, OTP, resend, logout/login pair | Is the OTP or session bound to the right user, device, and flow stage? |
| Reauth prompts | email/phone/password/2FA update, password confirmation endpoint | Can a hijacked session skip fresh password proof for sensitive changes? |
| SSO/SAML/OAuth | callback, host, ACS, RelayState, XMLRPC fallback, unsigned JWT, `state`, `nonce` | Is federated identity validated and bound to the intended client and session? |
| Subdomain trust | dangling CNAME, static host, auth redirect whitelist, cookie domain | Can a taken-over subdomain receive cookies, tokens, redirects, or trusted auth traffic? |
| Token leaks | CI logs, Docker images, mobile files, open redirects, path traversal, reset links | Can the leaked token authenticate, refresh, or reach privileged data? |
| 2FA/MFA | setup, disable, backup codes, enforcement groups, app/mobile parity | Can 2FA be disabled, bypassed, linked to another user, or skipped on another client? |
| Brute force | login, basic auth, WebDAV, OTP, username timing, lockout | Are throttles tied to account, IP, session, device, and credential type? |
| Client auth | bot key, client ID, app token, device token, launcher session | Does the server validate the secret and principal, or trust malformed client state? |
| Exposed panels | VPN, Jenkins, Actuator, Docker Registry, monitoring, admin, KVM | Does unauthenticated access reveal creds, files, images, jobs, sessions, or RCE paths? |

## Variant Playbook

- Replay auth requests with removed cookies, stale cookies, wrong user IDs, victim identifiers, empty auth fields, `null`, false/true toggles, missing token halves, and duplicate parameters.
- Block or follow redirects manually; request the post-login destination directly; compare browser-rendered behavior with raw HTTP responses.
- Change response-only values in the client and then verify whether the server actually issued a session or accepted a later privileged request.
- Swap OTP, phone, user ID, session token, device ID, and flow identifiers across attacker and victim sessions.
- Retry sensitive changes after login, after logout, after password change, after 2FA change, after session expiry, and from a fresh browser.
- Compare web, mobile, API, XMLRPC, WebDAV, legacy, regional, staging, and SSO routes for the same auth decision.
- Test federated auth parsing with altered host, callback, `redirect_uri`, `state`, `nonce`, RelayState, issuer, audience, signed vs unsigned token, and fallback local auth paths.
- Review cookie behavior: domain, path, Secure, HttpOnly, SameSite, duplicate cookie parsing, subdomain injection, session fixation, and token rotation.
- Check throttling across IP, account, username, session, device, User-Agent, endpoint, basic auth, OTP, and recovery flows.
- Inspect public artifacts for auth tokens: CI logs, Docker layers, mobile bundles, desktop app storage, old commits, debug pages, and downloadable backups.

## Confirmation Discipline

Authentication impact needs server-side control evidence, not just UI state.

Strong evidence includes:

- A clean browser receives a valid session without the expected credential, factor, or callback proof.
- A accesses a protected resource, admin page, API, file, or infrastructure panel without satisfying the intended auth gate.
- A performs a sensitive action after bypassing password reauth, MFA, SSO, OTP, or session validation.
- A logs in as B, binds a factor to B, changes B's auth settings, or obtains B's token.
- A stale, leaked, malformed, or client-controlled token remains accepted.
- A bypass works across direct HTTP requests, not only through modified client UI.

Rule out weak findings:

- The client UI changes but the server never accepts a privileged follow-up request.
- The endpoint is intentionally public and returns no sensitive data or state change.
- The token is expired, single-use, scoped harmlessly, or rejected by privileged endpoints.
- The redirect can be blocked but the protected resource still checks auth server-side.
- The account is attacker-created only and cannot claim another identity or privileged state.
- Rate-limit behavior is noisy but does not enable realistic guessing, lockout, enumeration, or bypass.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper auth-flow inventory, identity-state matrix, SSO/OAuth/SAML checks, OTP/MFA checks, session/cookie review, brute-force/throttling review, exposed infrastructure checklist, confirmation checklist, impact ranking, or remediation checklist.
