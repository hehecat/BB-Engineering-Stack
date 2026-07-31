# Request Smuggling Methodology

Use this reference to test HTTP parser desynchronization.

## 1. Stack inventory

Record CDN, WAF, reverse proxy, load balancer, origin, protocol versions, keep-alive, and cache behavior.

## 2. Variant families

Test CL.TE, TE.CL, TE.TE, duplicate CL, malformed TE, whitespace, casing, HTTP/2 downgrade, and pseudoheader ambiguity.

## 3. Impact checks

Review response queue poisoning, cache poisoning, auth bypass, internal path tunneling, credential capture, and request prefix injection.

## 4. Confirmation rules

Use controlled canaries and isolated accounts. Show parser disagreement plus a security boundary crossed.

## 5. Remediation checklist

- Normalize/reject ambiguous framing at the edge.
- Keep proxy/origin parser behavior consistent.
- Disable risky downgrade behavior.
- Close connections on malformed requests.
- Add desync regression tests.
