---
name: file-upload
description: Advanced file upload vulnerability testing methodology for bug bounty and application security work. Use when testing or reviewing unrestricted uploads, webshell upload, upload-to-RCE, stored XSS through files, SVG/image/PDF upload abuse, MIME/type validation bypass, extension bypass, archive extraction, upload SSRF, metadata abuse, path traversal in filenames, file overwrite, public storage exposure, and workflows where uploaded content is stored, processed, rendered, converted, or executed.
---

# File Upload Testing

## Core Posture

Treat uploads as a pipeline: accept, validate, store, process, render, serve, and delete. Test every step, not only extension filtering.

## Priority Patterns

- Webshell/RCE through executable upload, admin upload, plugin upload, or server-side processing.
- Stored XSS through SVG, HTML, image metadata, filename, content type, or preview pages.
- SSRF/file-read through upload processors, image fetchers, PDF/SVG rendering, and importers.
- Path traversal, overwrite, zip slip, symlink extraction, and archive expansion.
- Public storage leaks and weak access control on uploaded files.

## Assessment Loop

1. Inventory allowed file types, storage paths, processing jobs, public URLs, previews, exports, and deletion behavior.
2. Test validation: extension, MIME, magic bytes, filename, content, size, dimensions, archive structure, and metadata.
3. Test serving context: content type, content disposition, domain, CSP, cache, and cookies.
4. Test processors: thumbnails, converters, virus scanners, OCR, PDF/SVG/image renderers, and background jobs.
5. Confirm impact as execution, stored script, unauthorized file access, overwrite, SSRF, or sensitive data exposure.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Executable path | Can upload land where code executes? |
| Preview/render | Can content execute or fetch internal resources? |
| Filename | Can name affect paths, HTML, headers, or logs? |
| Archive | Can extraction escape directories or overwrite files? |
| Storage URL | Are private files public or guessable? |

## Variant Playbook

- Try double extensions, case changes, null-like suffixes, MIME mismatch, polyglots, and magic byte tricks.
- Test SVG/HTML/PDF/Office/image metadata and filename XSS.
- Test archive paths, symlinks, nested archives, large files, and decompression bombs carefully.
- Compare direct file URL, CDN URL, preview URL, download URL, and authenticated API access.
- Test delete/replace/race behavior and stale public URLs.

## Confirmation Discipline

Strong evidence shows execution, stored XSS, unauthorized file access, path overwrite, SSRF, or meaningful processing abuse. Rule out upload of inert files that are never served or processed dangerously.

## References

Read `references/advanced-methodology.md` only when the task needs deeper validation bypasses, renderer/processor review, storage access checks, archive review, confirmation, or remediation guidance.
