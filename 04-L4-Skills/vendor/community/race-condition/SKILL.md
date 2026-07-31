---
name: race-condition
description: Advanced race condition testing methodology for bug bounty and application security work. Use when testing or reviewing concurrent requests, double spending, duplicate redemption, multiple payout, email activation races, 2FA races, undeletable membership, follow/like counters, gift cards, coupons, balance changes, inventory, account state transitions, and workflows where simultaneous or reordered actions break locking, idempotency, or state consistency.
---

# Race Condition Testing

## Core Posture

Treat race conditions as state-transition failures. Test whether two or more valid requests executed close together can bypass uniqueness, locking, idempotency, or workflow ordering.

## Priority Patterns

- Value duplication: gift cards, coupons, credits, refunds, rewards, balances, and payouts.
- State transitions: activate email, verify phone, enable/disable MFA, delete member, follow/unfollow, invite accept, and account recovery.
- Approval and workflow state: pending-to-approved, duplicate payments, duplicate submissions, and job creation.
- Counter and relationship drift: likes, follows, comments, group members, referrals, and inventory.
- Client-side race: form callbacks, redirects, browser event ordering, and Safari/data URL oddities.

## Assessment Loop

1. Identify state-changing requests with uniqueness or one-time intent.
2. Establish baseline before/after state and idempotency behavior.
3. Send small synchronized bursts using identical or paired requests.
4. Test cross-endpoint races: create/delete, redeem/refund, verify/change, invite/remove, enable/disable.
5. Confirm durable duplicate value, forbidden state, inconsistent relationship, or bypassed one-time gate.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| One-time token | Can it be consumed twice? |
| Balance update | Is check-then-update atomic? |
| State pair | Can create/delete or enable/disable interleave? |
| Approval flow | Can two transitions bypass final validation? |
| Background job | Can duplicated jobs produce duplicated effects? |

## Variant Playbook

- Send identical requests concurrently, then paired opposing requests.
- Race across web/API/mobile endpoints for the same action.
- Race token resend/use, old/new email verification, and MFA setup/verify.
- Race object deletion with action, membership removal with access, and payment failure with activation.
- Confirm database state, UI state, emails, notifications, and downstream jobs.

## Confirmation Discipline

Strong evidence shows a durable state that cannot be produced sequentially. Rule out transient UI glitches, duplicate responses with one backend effect, and benign idempotent retries.

## References

Read `references/advanced-methodology.md` only when the task needs deeper state modeling, concurrency variants, confirmation, impact ranking, or remediation checks.
