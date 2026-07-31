---
name: graphql
description: Advanced GraphQL security testing methodology for bug bounty and application security work. Use when testing or reviewing GraphQL queries, mutations, subscriptions, schema exposure, resolver authorization, nested data leaks, IDOR/BOLA in variables, mutation aliasing DoS, batched operations, global node IDs, token scope mismatch, hidden admin operations, SSRF through GraphQL fields, and REST/GraphQL permission drift.
---

# GraphQL Testing

## Core Posture

Treat GraphQL as a resolver graph, not a single endpoint. Every field, nested object, mutation, alias, and node lookup needs its own authorization, validation, and cost control.

## Priority Patterns

- Data leaks: private emails, payment transactions, report metadata, private list members, billing docs, team fields, and nested admin data.
- Mutations: delete, copy, generate session, update role, add rules, verify phone, and account recovery operations.
- Authorization drift: REST denies while GraphQL resolver returns data; parent authorized but child field leaks.
- Token-scope mismatch: app or user token has narrower intended scope than GraphQL allows.
- DoS: mutation aliasing, deep nesting, batching, fragments, introspection-like expansion, and expensive connections.
- SSRF/injection: URL fields, preview queries, import/export mutations, filters, search, and custom scalar parsing.

## Assessment Loop

1. Inventory operations from traffic, bundles, persisted query names, mobile apps, and errors.
2. Map object IDs, global node IDs, variables, tenant selectors, cursors, and fragments.
3. Compare roles and tokens across the same query/mutation.
4. Test nested fields and resolver-specific authorization, not only top-level operation access.
5. Test cost and batching carefully with bounded aliases, depth, and list sizes.
6. Confirm leaked data, side effects, scope breakout, or resource impact.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| `node(id:)` | Can any global ID fetch private objects? |
| Nested field | Is parent auth reused incorrectly for child data? |
| Mutation input | Can role, tenant, owner, or object IDs be swapped? |
| Alias/batch | Can one request multiply work or actions? |
| Token scope | Does GraphQL ignore REST/API token limitations? |
| Hidden op | Are old/admin operation names still accepted? |

## Variant Playbook

- Swap IDs in variables, input objects, fragments, nested objects, and connection cursors.
- Request minimal vs expanded fields across roles.
- Try aliases, fragments, batching, old operation names, persisted query IDs, and introspection alternatives.
- Compare REST and GraphQL for the same action.
- Test deleted, archived, pending, private, cross-tenant, and removed-member objects.
- Bound DoS checks by small alias/depth increments and timing deltas.

## Confirmation Discipline

Strong evidence shows unauthorized field data, unauthorized mutation side effect, token scope breakout, or measurable cost amplification. Rule out public fields and accepted-but-ignored variables.

## References

Read `references/advanced-methodology.md` only when the task needs deeper operation inventory, resolver authorization matrix, mutation checks, batching/cost review, confirmation checklist, or remediation guidance.
