# SSRF Methodology

Use this reference to test backend URL-fetch boundaries.

## 1. Fetcher inventory

List previews, imports, exports, webhooks, callbacks, avatars, renderers, converters, OAuth controllers, analytics, and document processors.

## 2. Parser and network checks

Test schemes, redirects, DNS, IPv4/IPv6, localhost aliases, private IPs, userinfo, encoded hosts, and parser mismatches.

## 3. Blind channels

Use DNS, HTTP callback, timing, status, content length, titles, errors, and webhook logs.

## 4. Impact checks

Assess metadata credentials, internal admin panels, localhost APIs, file reads, cloud APIs, and RCE chains.

## 5. Remediation checklist

- Use strict URL allowlists after canonicalization.
- Block private/link-local/metadata ranges at egress.
- Revalidate after redirects and DNS resolution.
- Isolate fetchers from credentials.
- Log and rate-limit outbound fetches.
