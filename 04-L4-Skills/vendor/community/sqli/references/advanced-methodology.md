# SQL Injection Methodology

Use this reference to test database query-control boundaries.

## 1. Input inventory

List path, query, body, JSON, array, GraphQL, sort, filter, search, report, CSV, header, and stored inputs.

## 2. Confirmation methods

Use boolean differences, error messages, time delays, result count changes, and safe out-of-band callbacks where appropriate.

## 3. Impact paths

Assess data access, auth bypass, file read/write, command execution, stacked queries, and privileged database functions.

## 4. Second-order checks

Store payloads in profile, name, comment, import, config, and admin-managed fields; trigger reports/search/exports later.

## 5. Remediation checklist

- Use parameterized queries.
- Avoid dynamic SQL for identifiers.
- Validate sort/filter allowlists.
- Limit DB privileges.
- Regression-test query builders and reports.
