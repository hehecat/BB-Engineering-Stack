# File Upload Methodology

Use this reference to test upload pipelines.

## 1. Pipeline inventory

Record accepted types, validators, storage, URLs, processors, previews, conversions, metadata, and deletion lifecycle.

## 2. Validation checks

Test extension, MIME, magic bytes, filename, size, dimensions, archive structure, and content scanning.

## 3. Processing checks

Review thumbnailers, SVG/PDF renderers, OCR, virus scanners, importers, converters, and background jobs for SSRF/RCE/XSS.

## 4. Serving checks

Check content type, content disposition, CSP, cookies, cache, public/private storage, and access control.

## 5. Remediation checklist

- Store uploads outside executable paths.
- Use allowlisted types and content rewriting.
- Serve from isolated domains.
- Sanitize filenames and metadata.
- Sandbox processors and validate archives.
