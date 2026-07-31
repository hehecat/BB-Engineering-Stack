# Web Cache Methodology

Use this reference to test shared cache trust.

## 1. Cache inventory

Record CDN, reverse proxy, cache headers, cache status headers, TTL, purge, and static/dynamic path rules.

## 2. Poisoning checks

Test unkeyed headers, query parameters, path normalization, Host/Origin reflection, language, scheme, and cookies.

## 3. Deception checks

Test private pages with static suffixes, path confusion, extension tricks, and origin/CDN routing differences.

## 4. Confirmation rules

Use separate sessions and cache busters to prove shared cache impact.

## 5. Remediation checklist

- Key on all response-affecting inputs.
- Set private/no-store on sensitive pages.
- Use correct `Vary` headers.
- Normalize paths consistently.
- Avoid reflecting untrusted headers.
