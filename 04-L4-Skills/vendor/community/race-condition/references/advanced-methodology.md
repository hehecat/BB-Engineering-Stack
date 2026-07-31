# Race Condition Methodology

Use this reference to test concurrency-sensitive state transitions.

## 1. Candidate inventory

List one-time tokens, balance updates, redemptions, payments, invites, follows, deletes, approvals, recoveries, MFA, and background jobs.

## 2. Race types

Test identical request races, opposing action races, cross-endpoint races, stale-token races, and job duplication races.

## 3. Timing strategy

Use small controlled bursts, synchronize final bytes where possible, and compare with sequential baseline.

## 4. Confirmation rules

Confirm durable duplicate value, inconsistent membership, duplicated payout, bypassed approval, or impossible state.

## 5. Remediation checklist

- Use atomic database constraints and transactions.
- Make operations idempotent.
- Lock per object/user/token.
- Recheck authorization and state at commit time.
- Add concurrency regression tests.
