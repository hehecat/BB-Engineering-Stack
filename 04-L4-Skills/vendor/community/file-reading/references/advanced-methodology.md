# File Reading Methodology

Use this reference to test filesystem and file-fetch boundaries.

## 1. Input inventory

List filename, path, URL, archive entry, template, export HTML, image metadata, attachment, import, callback, and storage key inputs.

## 2. Namespace mapping

Identify server filesystem, container filesystem, client filesystem, storage bucket, cloud metadata, renderer sandbox, or internal service.

## 3. Traversal checks

Test encoding, mixed separators, absolute paths, symlinks, archive paths, Windows paths, Unicode normalization, and prefix bypasses.

## 4. Renderer checks

Review PDF/HTML/SVG/image converters for local file fetch, SSRF, external resources, and metadata-triggered reads.

## 5. Confirmation rules

Use controlled files first; then assess secrets such as configs, env vars, source, tokens, metadata, and tenant files.

## 6. Remediation checklist

- Canonicalize paths before policy checks.
- Use allowlisted storage IDs, not raw paths.
- Disable local file fetch in renderers.
- Sanitize archives and reject symlinks/traversal.
- Isolate converters and workers.
