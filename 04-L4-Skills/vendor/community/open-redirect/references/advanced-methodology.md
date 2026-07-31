# Open Redirect Methodology

Use this reference to assess redirect trust and chaining.

## 1. Redirect inventory

List redirect parameters, login/logout destinations, OAuth callbacks, SSO RelayState, QR URLs, mobile deeplinks, and error redirects.

## 2. Parser checks

Test scheme-relative URLs, encoded slashes, backslashes, userinfo, fragments, IDN, nested URLs, path traversal, trailing dots, and double encoding.

## 3. Trust chaining

Prioritize OAuth code leakage, SSO token leakage, app-link capture, phishing with auth context, SSRF, XSS, and cache poisoning chains.

## 4. Confirmation rules

Show the trusted origin sending a sensitive flow or token-bearing user to attacker-controlled destination.

## 5. Remediation checklist

- Use server-side destination IDs instead of raw URLs.
- Enforce exact allowlists after canonicalization.
- Strip tokens from URLs.
- Do not allow redirects in OAuth callback allowlists.
- Validate mobile and QR redirect targets.
