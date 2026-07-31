---
name: business-logic
description: Advanced business logic vulnerability testing methodology for bug bounty and application security work. Use when testing or reviewing workflow abuse, price or balance manipulation, approval bypass, abuse-report misuse, account recovery logic, invite or onboarding logic, state machine flaws, negative quantities, duplicate redemption, free purchases, moderation bypass, trust assumptions, and multi-step product flows where valid-looking actions can produce unauthorized business outcomes.
---

# Business Logic Testing

## Core Posture

Treat business logic bugs as broken product rules, not parser bugs. Identify the intended invariant, then test whether different orderings, states, roles, quantities, retries, or cross-feature combinations violate it.

Use public case lessons as prioritization signals. Choose inspection methods from the user's artifacts and target type; do not narrow the skill to one product area.

## Priority Patterns

- Money and value: negative quantities, balance manipulation, discounts, refunds, gift cards, credits, coupons, reward points, free bookings, and payment-state mismatches.
- Workflow state: pending-to-approved, unpaid-to-paid, inactive-to-active, deleted-but-usable, duplicate redemption, and review/moderation bypass.
- Account and recovery logic: email change plus reset, identity merge, unverified account trust, invitation acceptance, and onboarding state confusion.
- Abuse of protective features: report abuse, block, moderation, blacklist, sanctions, account deletion, and account lockout used against other users.
- Cross-feature chains: export/import, templates, project copy, clone, fork, restore, migration, and shared resource propagation.
- Hidden or stale states: old tokens, retired UI flows, mobile-only paths, previous role membership, and objects removed from UI but still actionable.

## Assessment Loop

1. Define the product invariant: who should be able to do what, in which state, and under which business precondition.
2. Build state pairs: paid/unpaid, verified/unverified, pending/approved, active/deleted, owner/member, first-use/reuse, and before/after cancellation.
3. Capture the normal flow from UI and API, including background jobs, emails, webhooks, notifications, and downstream effects.
4. Mutate sequence, timing, quantity, state, and actor while keeping requests syntactically valid.
5. Confirm impact in business terms: value gained, review skipped, object copied, victim affected, state persisted, or downstream system trusted the bad state.

## High-Value Cues

| Family | Look for | Ask |
| --- | --- | --- |
| Pricing/value | quantity, amount, discount, balance, currency, refund | Can valid fields create impossible value? |
| Approval state | approved, reviewed, active, status, payment | Can A skip a human or payment gate? |
| Recovery/identity | email, phone, owner, merge, reset | Can one flow change who owns another flow? |
| Abuse features | report, block, delete, flag, hide | Can a safety tool become an attack tool? |
| Duplication | copy, clone, template, restore, import | Does copying preserve private or privileged state? |
| Stale state | deleted, canceled, expired, old link | Does a retired state still authorize actions? |

## Variant Playbook

- Reorder steps: perform step 3 before step 2, skip confirmation, repeat a single step, or resume an old flow.
- Replay the same action after cancellation, deletion, logout, payment failure, role change, or token expiry.
- Send boundary values: negative numbers, zero, decimals, huge values, duplicate IDs, mixed currencies, and empty arrays.
- Compare UI restrictions with direct API calls and mobile/legacy endpoints.
- Test whether background jobs, emails, exports, and webhooks trust manipulated state.
- Combine independent features: invite plus reset, template plus private project, abuse report plus deletion, import plus permissions.

## Confirmation Discipline

Strong evidence shows a product invariant broken: free value, unauthorized copy, skipped approval, victim-side effect, durable state change, or protective feature abuse.

Rule out weak findings: UI-only inconsistencies, self-only harmless state, ignored parameters, intentionally flexible workflows, or changes that are corrected before downstream impact.

## References

Read `references/advanced-methodology.md` only when the task needs a deeper workflow matrix, value-flow review, state-machine review, confirmation checklist, impact ranking, or remediation checklist.
