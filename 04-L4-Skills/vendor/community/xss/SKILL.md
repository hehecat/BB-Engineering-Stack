---
name: xss
description: Advanced cross-site scripting testing methodology for bug bounty and application security work. Use when testing or reviewing reflected XSS, stored XSS, DOM XSS, cache-poisoned XSS, OAuth/login-flow XSS, admin-context XSS, markdown/CMS/wiki XSS, chat/client XSS, SVG/file upload XSS, postMessage XSS, CSP bypass, mobile/WebView XSS, and workflows where attacker-controlled input executes JavaScript in another user's browser or a privileged admin context.
---

# XSS Testing

## Core Posture

Treat XSS as execution context control. Identify source, sink, parser, encoding layer, trust boundary, and victim context before judging impact.

## Priority Patterns

- Stored XSS in profiles, wiki pages, comments, chats, admin dashboards, uploads, and cached pages.
- Reflected XSS in login/OAuth/search/error paths with account-token exposure.
- DOM XSS through URL, hash, postMessage, local storage, and client-side templates.
- File/content XSS through SVG, images, PDFs, Markdown, HTML sanitizers, and filename rendering.
- Cache poisoning to stored XSS and privileged/admin-context XSS.

## Assessment Loop

1. Inventory sources and sinks: parameters, body fields, headers, cookies, stored content, files, postMessage, and cache.
2. Determine context: HTML, attribute, JavaScript, URL, CSS, SVG/XML, Markdown, template, or DOM sink.
3. Test harmless markers and context breaks before payloads.
4. Check sanitization, encoding, CSP, Trusted Types, and browser-specific behavior.
5. Confirm execution in the intended victim context and assess reachable secrets/actions.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Stored content | Does low-role input execute for users/admins? |
| Login/OAuth | Can script access tokens, codes, or linked-account flows? |
| DOM sink | Does client route/hash/message reach dangerous APIs? |
| File upload | Does uploaded content execute on trusted origin? |
| Cache | Can XSS be stored for many users through cache? |

## Variant Playbook

- Test context-specific escaping, nested parsers, double decoding, template interpolation, and sanitizer mutation.
- Compare web/mobile, old browsers, CSP variants, and admin rendering.
- Test SVG/Markdown/HTML/filename/metadata and uploaded previews.
- Probe postMessage origin checks and JSON parsing.
- Chain to meaningful actions: token theft, CSRF, account takeover, admin data, or privileged operations.

## Confirmation Discipline

Strong evidence shows JavaScript execution in a security-relevant origin and victim context. Rule out self-XSS, inert markup, sandboxed origins with no impact, and payloads requiring unrealistic victim developer action.

## References

Read `references/advanced-methodology.md` only when the task needs deeper context analysis, DOM/postMessage review, sanitizer/CSP bypass, file-upload XSS, confirmation, or remediation checks.
