# XXE Methodology

Use this reference to test XML entity resolution boundaries.

## 1. Parser inventory

List XML bodies, SOAP, SAML, SXMP, SVG, Office, PDF, XMP metadata, uploads, imports, converters, and background processors.

## 2. Entity checks

Test harmless DTD/entity behavior, external general entities, parameter entities, external DTDs, and parser error output.

## 3. Blind channels

Use controlled DNS/HTTP callbacks, timing, error differences, and async processing artifacts.

## 4. Impact checks

Assess local file read, SSRF, metadata access, internal services, config disclosure, source disclosure, and credential exposure.

## 5. Remediation checklist

- Disable DTDs and external entity resolution.
- Use hardened XML parser settings.
- Block network/file access in parsers.
- Sanitize SVG/Office/PDF metadata processors.
- Isolate converters and background parsers.
