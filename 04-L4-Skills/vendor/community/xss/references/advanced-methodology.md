# XSS Methodology

Use this reference to test browser execution boundaries.

## 1. Source and sink inventory

List URL, hash, query, body, headers, cookies, stored content, uploads, cache, postMessage, local storage, and API responses.

## 2. Context analysis

Classify HTML text, attribute, JavaScript string, URL, CSS, SVG/XML, Markdown, template, and DOM API contexts.

## 3. Defense review

Check output encoding, sanitizers, CSP, Trusted Types, sandboxed origins, cookie flags, and framework escaping.

## 4. Impact checks

Assess token access, account actions, admin context, OAuth/login flows, stored reach, cache reach, and sensitive APIs.

## 5. Remediation checklist

- Encode by context.
- Sanitize rich content with proven libraries.
- Avoid dangerous DOM sinks.
- Enforce CSP/Trusted Types defensively.
- Isolate uploaded active content.
