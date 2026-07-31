---
name: xxe
description: Advanced XML External Entity (XXE) testing methodology for bug bounty and application security work. Use when testing or reviewing XML parsers, SOAP/SAML/SXMP processors, Office/PDF/image metadata parsers, XMP metadata in JPEGs, SVG/XML uploads, IVR or phone-to-XML workflows, document import/export, blind XXE, out-of-band XXE, local file disclosure, SSRF through XML entities, parser configuration mistakes, and workflows where attacker-controlled XML or metadata can resolve external entities.
---

# XXE Testing

## Core Posture

Treat XXE as unsafe XML entity resolution. Identify where XML-like input is parsed, whether external entities or DTDs are allowed, and what filesystem or network the parser can reach.

## Priority Patterns

- Direct XML endpoints: SOAP, SXMP, API XML, legacy upload, and dynamic page processors.
- File metadata: XMP in JPEG/PDF, SVG, Office documents, and imported media.
- Blind XXE: out-of-band DNS/HTTP callbacks, timing, and error side channels.
- Local file disclosure: parser reads application config, environment files, source, credentials, or system files.
- SSRF: XML parser fetches internal URLs, metadata endpoints, or localhost services.
- Non-obvious flows: IVR/phone-to-XML, document conversion, import/export, and background processors.

## Assessment Loop

1. Inventory XML-capable inputs: XML bodies, SOAP, SAML, SVG, Office, PDF, XMP metadata, uploads, imports, and converters.
2. Determine parser behavior: DTD allowed, external entities, parameter entities, network access, file access, and error output.
3. Start with harmless entity expansion or out-of-band canary.
4. Test file and network reachability only with controlled, low-risk targets.
5. Confirm disclosed content, callback, parser error, or SSRF side channel.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| XML upload | Is uploaded XML parsed server-side? |
| Metadata | Does converter parse XMP/SVG/Office entities? |
| SOAP/SAML | Are DTDs or external entities enabled? |
| Blind parser | Can DNS/HTTP callback prove resolution? |
| File/SSRF | Can parser reach local files or internal URLs? |

## Variant Playbook

- Test external general entities, parameter entities, external DTDs, and blind callbacks.
- Place XML in body, multipart file, SVG, XMP metadata, Office docs, and import fields.
- Compare sync response, async conversion, preview, export, and error handling.
- Test URL schemes and redirects cautiously.
- Check parser-specific defaults and hardening.

## Confirmation Discipline

Strong evidence shows external entity resolution with file read, SSRF, or reliable out-of-band callback from the server. Rule out client-side XML parsing and literal entity echo.

## References

Read `references/advanced-methodology.md` only when the task needs deeper parser inventory, metadata/file-format checks, blind XXE confirmation, SSRF/file-read impact, or remediation guidance.
