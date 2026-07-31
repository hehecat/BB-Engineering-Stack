# CSRF Methodology

Use this reference to test browser-mediated authenticated state changes.

## 1. Action inventory

List all create, update, delete, link, unlink, invite, approve, payment, admin, security-setting, and OAuth consent actions.

## 2. Defense review

Check synchronizer tokens, double-submit tokens, token binding to session/action, Origin/Referer checks, SameSite, CORS, and content-type assumptions.

## 3. Delivery modes

Try forms, auto-submit forms, images, script tags, top-level navigation, redirects, iframes, mobile deeplinks, and same-site subdomains.

## 4. JSON/API checks

Test simple content types, method override, multipart, duplicate parameters, preflight behavior, and token validation order.

## 5. Confirmation rules

Confirm durable side effects from a cross-site trigger under victim credentials.

## 6. Remediation checklist

- Require CSRF tokens on all cookie-auth state changes.
- Bind tokens to session and action.
- Enforce Origin/Referer for sensitive actions.
- Use SameSite defensively, not as the only control.
- Avoid state-changing GET endpoints.
