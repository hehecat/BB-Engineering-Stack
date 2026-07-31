---
name: mfa-bypass
description: Advanced MFA and 2FA bypass testing methodology for bug bounty and application security work. Use when testing or reviewing two-factor authentication, MFA enrollment, MFA disable flows, backup codes, recovery codes, remembered devices, enforcement policies, race conditions, blank or reused codes, session persistence after MFA changes, mobile/web MFA parity, embedded forms, and workflows where a user can bypass, weaken, remove, or satisfy MFA incorrectly.
---

# MFA Bypass Testing

## Core Posture

Treat MFA as a second proof bound to a user, session, device, action, and time. Test enrollment, enforcement, recovery, disable, and remembered-device flows, not only the login challenge.

## Priority Patterns

- Challenge bypass: blank codes, reused codes, wrong-code acceptance, race conditions, and response manipulation.
- Enrollment abuse: enabling MFA without verified email, linking a factor to another user, or setup without reauth.
- Disable/recovery abuse: disabling 2FA without password, backup code leakage, recovery reset gaps, and support flows.
- Enforcement gaps: embedded forms, mobile/web differences, group enforcement bypass, API routes without MFA, and old sessions.
- Session persistence: sessions created before MFA remains valid after MFA activation or policy change.

## Assessment Loop

1. Map MFA states: not enrolled, enrolling, enrolled, enforced, remembered device, recovery mode, disabled, and admin-enforced.
2. Capture login, setup, verify, backup, recovery, disable, device trust, and policy enforcement flows.
3. Track factor binding: user, session, device, phone/email, tenant, challenge ID, and expiry.
4. Test swaps, replays, races, blank values, stale sessions, and client differences.
5. Confirm access to protected actions after bypassing the required factor.

## High-Value Cues

| Cue | Ask |
| --- | --- |
| Blank/reused code | Does server validate code and challenge together? |
| Factor linking | Can A bind A's factor to B? |
| Disable flow | Is password/fresh proof required? |
| Enforcement | Do all clients and embedded forms require MFA? |
| Old sessions | Are pre-MFA sessions invalidated? |

## Variant Playbook

- Submit blank, null, old, wrong, repeated, padded, and parallel MFA codes.
- Swap challenge IDs, user IDs, phone IDs, session tokens, and device IDs.
- Race setup, verify, resend, disable, and backup-code generation.
- Compare web, mobile, API, embedded, SSO, and recovery flows.
- Test old sessions after enabling MFA or admin enforcement.

## Confirmation Discipline

Strong evidence shows access to MFA-protected account state or actions without a valid second factor. Rule out self-only setup quirks with no bypass and UI-only enforcement differences.

## References

Read `references/advanced-methodology.md` only when the task needs deeper factor-state matrix, challenge binding review, race checks, enforcement parity, confirmation, or remediation guidance.
