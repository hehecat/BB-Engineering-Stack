---
name: ssti
description: Advanced server-side template injection testing methodology for bug bounty and application security work. Use when testing or reviewing template rendering, email templates, CMS templates, preview/render APIs, Smarty/Jinja/Twig/ERB/Ruby/Python template engines, path traversal plus SSTI, SSTI-to-RCE, reflected or stored template execution, user-controlled template variables, and workflows where attacker input is evaluated by a server-side template engine.
---

# SSTI Testing

## Core Posture

Treat SSTI as server-side expression evaluation. Identify the template engine, where user input enters the template, and whether execution reaches objects, filesystem, commands, or secrets.

## Priority Patterns

- Email templates, CMS pages, signup/name fields, preview systems, and custom content blocks.
- Reflected and stored template evaluation in admin or backend contexts.
- Path traversal plus template selection or include.
- Template engine escapes that allow sandbox escape or command execution.
- Security tooling queries and code scanning patterns for SSTI.

## Assessment Loop

1. Find rendered inputs: names, template bodies, CMS fields, email content, preview parameters, imports, and themes.
2. Use harmless arithmetic or marker expressions to identify evaluation.
3. Fingerprint engine carefully by syntax and error behavior.
4. Test context and sandbox boundaries with non-destructive introspection.
5. Confirm impact as server-side data access, file read, command execution, or privileged rendering.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Template preview | Is user-controlled template content rendered server-side? |
| Email/CMS | Can low-role input execute in a trusted render context? |
| Engine error | Does syntax error reveal engine or object model? |
| Sandbox | Can object traversal escape restrictions? |
| Stored render | Does payload execute later for admin or users? |

## Variant Playbook

- Try engine-specific harmless markers for Jinja, Twig, Smarty, ERB, Ruby, Java, and JavaScript engines.
- Test reflected and stored contexts separately.
- Compare plain text, HTML, Markdown, email, PDF, and CMS preview renderers.
- Look for include/template-name/path controls and theme upload paths.
- Escalate only after confirming engine and context.

## Confirmation Discipline

Strong evidence shows server-side expression evaluation and meaningful access beyond intended interpolation. Rule out client-side template execution and literal echo.

## References

Read `references/advanced-methodology.md` only when the task needs deeper engine fingerprinting, stored/render context review, sandbox escape analysis, confirmation, or remediation guidance.
