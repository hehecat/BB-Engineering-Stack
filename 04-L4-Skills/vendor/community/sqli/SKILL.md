---
name: sqli
description: Advanced SQL injection testing methodology for bug bounty and application security work. Use when testing or reviewing SQLi, blind SQLi, time-based SQLi, error-based SQLi, second-order SQLi, GraphQL or API filter SQLi, search/report/admin SQLi, JSON or array parameter SQLi, header-based SQLi, SQLi-to-file-read, SQLi-to-RCE, and workflows where user-controlled input reaches database queries or query builders unsafely.
---

# SQL Injection Testing

## Core Posture

Treat SQLi as query-structure control. Identify which input affects SQL syntax, logic, timing, errors, or backend query behavior, then confirm with minimal, bounded evidence.

## Priority Patterns

- Search, filters, reports, dashboards, analytics, admin lists, and CSV/JSON conversion.
- API parameters, array parameters, JSON bodies, GraphQL filters, headers, and User-Agent.
- Blind/time-based paths with no visible output.
- SQLi-to-RCE or file read through database features, stacked queries, or privileged functions.
- Second-order SQLi through stored fields later used in admin or reporting queries.

## Assessment Loop

1. Inventory query-like inputs and compare response differences, errors, timing, and result counts.
2. Identify database hints from errors, behavior, syntax, and stack traces.
3. Confirm injection with harmless boolean, error, or timing tests.
4. Explore impact only enough to determine data sensitivity, auth boundary, or execution potential.
5. Check whether filters, arrays, JSON, GraphQL, and headers reach the same query builder.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Search/filter | Does syntax alter result count or timing? |
| Arrays/JSON | Are nested values interpolated unsafely? |
| Admin/report | Does low-role input reach privileged query paths? |
| Blind path | Can timing confirm control? |
| DB feature | Can SQLi read files, write files, or execute code? |

## Variant Playbook

- Test strings, numbers, arrays, repeated parameters, JSON values, sort/order fields, and headers.
- Compare boolean true/false, syntax error, time delay, and out-of-band behavior.
- Test encoded payloads, comment styles, database-specific syntax, and type confusion.
- Check stored inputs later rendered in reports, exports, admin search, or background jobs.

## Confirmation Discipline

Strong evidence shows controlled SQL logic, timing, error, data extraction, file access, or execution path. Rule out generic errors, WAF blocks, and response differences unrelated to query behavior.

## References

Read `references/advanced-methodology.md` only when the task needs deeper query-surface inventory, blind SQLi confirmation, second-order checks, SQLi-to-RCE/file-read review, or remediation guidance.
