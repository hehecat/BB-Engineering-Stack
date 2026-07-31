---
name: subdomain-takeover
description: Advanced subdomain takeover testing methodology for bug bounty and application security work. Use when testing or reviewing dangling DNS records, unclaimed cloud/CDN/storage/app-service resources, CloudFront/Heroku/GitHub Pages/Azure/S3/Fastly-style takeovers, authentication bypass through trusted subdomains, cookie scope abuse, OAuth redirect allowlist abuse, staging subdomain takeover, and chains where a controlled subdomain can steal tokens, host trusted content, bypass auth, or affect users.
---

# Subdomain Takeover Testing

## Core Posture

Treat subdomain takeover as trusted-origin control. The impact depends on what the parent product trusts from that host: cookies, redirects, OAuth callbacks, CORS, scripts, users, or brand trust.

## Priority Patterns

- Dangling DNS to cloud/CDN/app platforms.
- Auth-adjacent subdomains trusted by SSO, OAuth, static assets, or redirect allowlists.
- Cookie scope across parent domain and subdomains.
- Staging/storybook/dev/docs hosts with production trust.
- Multiple takeovers across regions or environments.

## Assessment Loop

1. Inventory DNS records, CNAME targets, cloud providers, errors, and abandoned services.
2. Verify takeover feasibility without claiming unrelated live resources blindly.
3. Map trust: cookies, CORS, OAuth redirects, script inclusion, CSP allowlists, SSO, and user-facing links.
4. Confirm controlled content on the subdomain.
5. Assess chain impact: token theft, auth bypass, account takeover, phishing with trusted domain, or data access.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Dangling CNAME | Can the resource be claimed by another account? |
| Cookie domain | Will parent-domain cookies be sent? |
| OAuth allowlist | Is the subdomain an accepted callback or redirect? |
| Static trust | Is it allowed by CSP, scripts, or SSO assets? |
| Staging/dev | Does it share auth or production trust? |

## Variant Playbook

- Check CNAME, ALIAS, A/AAAA, NS, MX, TXT verification, and provider-specific error pages.
- Test wildcard DNS and regional variants.
- Review CSP, CORS, cookie domain/path, OAuth callback allowlists, and SSO redirect hosts.
- Look for links from production UI or emails to the subdomain.
- Chain only after proving controlled content.

## Confirmation Discipline

Strong evidence shows controlled content plus meaningful trust or user impact. Rule out inactive DNS with no claim path, parked pages owned by the program, and brand-only impact with no security chain.

## References

Read `references/advanced-methodology.md` only when the task needs deeper DNS/provider checks, trust-chain review, auth/OAuth chaining, confirmation, or remediation guidance.
