# Business Logic Methodology

Use this reference to test product invariants across multi-step flows.

## 1. Workflow inventory

Record actor, object, state, prerequisite, action, side effect, and downstream consumer for every step. Include UI, API, emails, background jobs, webhooks, exports, and mobile routes.

## 2. State matrix

Test before/after states: unpaid, paid, pending, approved, rejected, deleted, restored, archived, canceled, refunded, verified, unverified, invited, accepted, blocked, and removed.

## 3. Value-flow checks

Review quantity, price, tax, currency, discount, credits, wallet balance, coupon, gift card, refund, subscription period, booking duration, and shipping fields. Confirm server-side recomputation.

## 4. Sequence checks

Try skipping, repeating, reordering, pausing, resuming, and racing steps. Use old links and stale tokens after the flow advances.

## 5. Cross-feature checks

Combine features that were designed separately: template copy, import/export, sharing, invitations, recovery, abuse reporting, moderation, migration, and restore.

## 6. Confirmation rules

Confirm durable business impact: money, access, private data, victim effect, moderation effect, approval bypass, or system-of-record mutation.

## 7. Remediation checklist

- Enforce product invariants server-side.
- Recompute financial and approval state.
- Treat workflow state transitions as policy decisions.
- Make stale links and retired states fail closed.
- Add regression tests for ordering, replay, stale state, negative values, duplicate redemption, and downstream jobs.
