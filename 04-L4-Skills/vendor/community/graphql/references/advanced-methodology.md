# GraphQL Methodology

Use this reference to test GraphQL resolver, mutation, and query-cost boundaries.

## 1. Operation inventory

Collect operation names, variables, persisted query IDs, fragments, node IDs, connection cursors, schema hints, and mobile/web/client documents.

## 2. Authorization matrix

Test anonymous, user A/B, roles, tenants, removed users, API tokens, app tokens, and admin/staff paths for each resolver and nested field.

## 3. Mutation review

Focus on create/update/delete/copy/verify/generate-session/add-rule operations. Swap object, owner, tenant, role, and lifecycle state.

## 4. Cost review

Test bounded aliases, nested fragments, large lists, connection traversal, batching, and repeated mutations. Look for missing query cost limits.

## 5. Drift checks

Compare REST, mobile, old GraphQL operation names, persisted queries, and admin UI routes for the same object/action.

## 6. Remediation checklist

- Authorize every resolver and nested field.
- Scope node lookups by caller and tenant.
- Enforce query depth, complexity, aliases, and rate limits.
- Validate mutation input server-side.
- Regression-test REST/GraphQL parity.
