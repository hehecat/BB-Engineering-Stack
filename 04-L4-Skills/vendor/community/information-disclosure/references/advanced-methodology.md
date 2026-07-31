# Information Disclosure Methodology

Use this reference to identify unintended audiences for sensitive data.

## 1. Data inventory

Classify PII, credentials, tokens, private content, metadata, internal paths, logs, configs, stack traces, source maps, backups, and tenant identifiers.

## 2. Audience matrix

Compare anonymous, user A/B, roles, tenants, mobile/web, API key, removed user, and admin responses.

## 3. Response surfaces

Review JSON, HTML preloads, GraphQL, exports, PDFs, CSVs, emails, notifications, errors, debug pages, Sentry, source maps, and cache.

## 4. Chaining value

Ask whether leaked data enables IDOR, ATO, OAuth abuse, phishing, internal targeting, support impersonation, or tenant enumeration.

## 5. Remediation checklist

- Return only fields needed by the caller.
- Strip debug data from production.
- Protect directories, buckets, logs, and backups.
- Set private cache headers.
- Regression-test field visibility by role and tenant.
