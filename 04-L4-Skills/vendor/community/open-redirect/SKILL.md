---
name: open-redirect
description: Advanced open redirect testing methodology for bug bounty and application security work. Use when testing or reviewing redirect URL parameters, login/logout redirects, OAuth redirect chains, SSO callbacks, payment or QR-code redirects, mobile deeplinks, URL parser mismatches, double encoding, host allowlist bypasses, and chains where redirection leads to token theft, account takeover, phishing, SSRF, XSS, or trusted-domain abuse.
---

# Open Redirect Testing

## Core Posture

Treat open redirect as trust transfer. The impact depends on what trust the redirecting origin carries: OAuth callback, login session, token, cookie, QR scan, mobile handoff, or user reputation.

## Priority Patterns

- OAuth/SSO redirects leaking codes, tokens, or trusted callback control.
- Login/logout redirects used for phishing or session/token theft.
- QR-code and mobile deeplink redirects that bridge apps or browsers.
- Allowlist bypass through path confusion, scheme confusion, double encoding, userinfo, protocol-relative URLs, and IDN.
- Chains into XSS, SSRF, cache poisoning, or account takeover.

## Assessment Loop

1. Inventory redirect parameters, headers, callback fields, QR links, mobile links, and post-login destinations.
2. Identify trust carried through the redirect: auth code, token, Referer, cookies, user click, or allowlisted host.
3. Test parser and allowlist variants.
4. Chain only where the redirect reaches sensitive auth, token, or trusted-domain behavior.
5. Confirm token/code leakage, wrong destination, or meaningful user/security impact.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| OAuth/SSO | Can redirect steal code, token, or state? |
| Login/logout | Can trusted origin send users to attacker content? |
| Mobile/QR | Does scan or deeplink trust the redirect destination? |
| Allowlist | Can parser mismatch escape a trusted domain? |
| Chaining | Does redirect enable XSS, SSRF, cache, or ATO? |

## Variant Playbook

- Try `//host`, encoded slashes, backslashes, userinfo, fragments, nested URLs, double encoding, IDN, trailing dots, and mixed case.
- Test `next`, `redirect`, `return_to`, `callback`, `continue`, `url`, `target`, `redirect_uri`, and logout parameters.
- Chain trusted redirect into OAuth, SSO, app links, QR flows, and token-bearing paths.
- Compare browser, server, mobile, CDN, and backend URL parsers.

## Confirmation Discipline

Strong evidence shows security impact beyond arbitrary navigation: token/code theft, auth chain bypass, trusted-domain phishing with sensitive context, or useful chaining. Rule out low-trust cosmetic redirects.

## References

Read `references/advanced-methodology.md` only when the task needs deeper parser bypasses, OAuth/SSO chaining, mobile/QR review, confirmation, or remediation checks.
