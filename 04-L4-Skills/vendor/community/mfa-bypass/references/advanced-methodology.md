# MFA Bypass Methodology

Use this reference to test factor binding and enforcement.

## 1. State matrix

Track not enrolled, pending setup, enrolled, enforced, remembered, recovery, disabled, old session, and admin-policy states.

## 2. Binding checks

Bind factor to user, session, challenge, device, phone/email, tenant, purpose, and expiry.

## 3. Bypass checks

Test blank code, replay, race, challenge swap, factor linking, disable without password, recovery reset, embedded forms, API-only access, and old sessions.

## 4. Client parity

Compare web, mobile, desktop, API, SSO, old app versions, and embedded submission forms.

## 5. Remediation checklist

- Bind MFA challenges to user/session/device.
- Invalidate old sessions after MFA changes.
- Require fresh proof to disable MFA.
- Enforce MFA on all clients and APIs.
- Rate-limit and expire challenges.
