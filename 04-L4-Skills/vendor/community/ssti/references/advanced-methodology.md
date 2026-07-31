# SSTI Methodology

Use this reference to test server-side template execution.

## 1. Surface inventory

List email templates, CMS fields, previews, themes, imports, names, custom blocks, Markdown/HTML renderers, and PDF generators.

## 2. Fingerprinting

Use harmless arithmetic/marker payloads and syntax errors to identify engine and context.

## 3. Context review

Differentiate literal echo, client-side templates, server templates, sandboxed templates, and privileged admin renderers.

## 4. Impact checks

Assess object access, file read, environment variables, command execution, SSRF, and stored admin-context execution.

## 5. Remediation checklist

- Avoid rendering user-controlled templates.
- Use safe variable interpolation.
- Sandbox engines and remove dangerous objects.
- Separate template authorship by role.
- Regression-test template contexts.
