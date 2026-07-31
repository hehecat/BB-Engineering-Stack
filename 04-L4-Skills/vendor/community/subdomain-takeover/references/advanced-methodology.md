# Subdomain Takeover Methodology

Use this reference to test dangling DNS and trusted-origin abuse.

## 1. DNS inventory

Collect CNAME, ALIAS, A/AAAA, NS, MX, TXT, wildcard, staging, regional, and old subdomains.

## 2. Provider checks

Identify cloud/CDN/app-service error fingerprints and whether another account can claim the resource.

## 3. Trust review

Check cookies, CORS, CSP, OAuth redirects, SSO callbacks, static script trust, email links, and production UI links.

## 4. Confirmation rules

Confirm controlled content and a security-relevant trust path.

## 5. Remediation checklist

- Remove dangling DNS.
- Verify cloud resource ownership.
- Narrow cookie domains.
- Restrict OAuth/CORS/CSP allowlists.
- Monitor DNS for drift.
