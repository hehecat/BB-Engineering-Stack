---
name: file-reading
description: Advanced file read and path traversal testing methodology for bug bounty and application security work. Use when testing or reviewing local file inclusion, arbitrary file read, path traversal, SSRF-to-file-read, PDF/HTML export file inclusion, archive extraction traversal, client download path traversal, container or host file disclosure, metadata file access, and workflows where user-controlled paths, URLs, filenames, or rendering content can expose restricted files.
---

# File Reading Testing

## Core Posture

Treat file-read bugs as boundary failures between user input and filesystem, URL fetchers, renderers, archives, containers, or local clients. Identify which file namespace is reachable and whose secrets live there.

## Priority Patterns

- Server-side file reads: LFI, path traversal, template includes, PDF/HTML export inclusion, and image/SVG metadata processing.
- SSRF-to-file-read: `file://`, cloud metadata, internal URLs, localhost services, and renderer fetches.
- Archive and upload paths: zip slip, tar traversal, filename normalization, symlink handling, and extraction overwrite.
- Client-side file exposure: desktop/mobile path traversal, download attachment writes, local token/config leaks.
- Container/host boundaries: worker escape, mounted secrets, `/proc`, environment files, service configs, and source code.

## Assessment Loop

1. Find path-like inputs: filename, URL, attachment, import, export, template, archive entry, image metadata, PDF HTML, and callback fields.
2. Determine parser and namespace: server FS, container FS, client FS, cloud metadata, renderer sandbox, or storage bucket.
3. Test normalization differences: encoded traversal, mixed separators, absolute paths, symlinks, archive paths, and URL schemes.
4. Confirm with low-risk known files or controlled markers before sensitive targets.
5. Assess impact by reachable secrets, credentials, source code, configs, tokens, and cross-tenant files.

## High-Value Cues

| Family | Ask |
| --- | --- |
| Export/render | Can HTML/PDF/SVG cause backend file fetch? |
| Upload/archive | Can filenames escape intended directories? |
| URL fetch | Are `file://`, localhost, metadata, or redirects followed? |
| Client app | Can downloaded files write or read outside the safe folder? |
| Container | Are host mounts, secrets, or source files readable? |

## Variant Playbook

- Try `../`, encoded traversal, double encoding, mixed slash/backslash, absolute paths, null-like suffixes, and path prefix tricks.
- Test symlinks, zip/tar entries, nested archives, long names, Unicode normalization, and Windows drive paths.
- Test renderer inputs: HTML `iframe/img/link`, SVG external entities, CSS `url()`, PDF conversion, and metadata.
- Compare web, mobile, desktop, worker, and export services.
- Follow redirect chains from allowed URL schemes or hosts.

## Confirmation Discipline

Strong evidence shows file contents or a controlled marker from outside the intended directory/tenant/sandbox. Rule out path echo, not-found differences, and public files.

## References

Read `references/advanced-methodology.md` only when the task needs deeper traversal, archive, renderer, SSRF-to-file, client-app, container, confirmation, or remediation checks.
