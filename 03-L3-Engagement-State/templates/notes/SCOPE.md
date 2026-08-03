# Scope And Rules

Reviewed: 2026-01-01T00:00:00Z
Revision: 1

## Authorization Source

- Status: pending
- Source: user instruction and the referenced program, competition, or lab rules
- Reference: recorded program page, challenge statement, contract, or local fixture
- Engagement type: bug bounty

## In-Scope Assets

| Asset or pattern | Type | Conditions |
| --- | --- | --- |
| example.invalid | web | Replace during engagement creation |

## Out-Of-Scope Assets

| Asset or pattern | Reason |
| --- | --- |
| No explicit exclusions recorded | Recheck the referenced rules before adding adjacent assets |

## Candidate Assets

Discovered relationship is not authorization. Record provenance here and move
an asset to In-Scope only with a written source and Scope revision.

| Asset or pattern | Type | Provenance | Active testing |
| --- | --- | --- | --- |
| None recorded | other | none | prohibited until promoted |

## Rate And Automation Rules

- Follow the written program or competition rate rules.
- No additional numeric limit was present in the initialization input.

## Identity And Request Marking

- Request identification: disabled by the generic profile
- Required headers or user-agent format: none recorded
- Test-account requirements: none recorded

## Side-Effect And Data Rules

- Use controlled test accounts and reversible test data where applicable.
- Stop repeated side effects once the required proof is captured.
- Keep credentials and long-lived tokens out of shared artifacts.

### Default Production Action Budget

Written program rules and explicit revisions below override these defaults.

| Action | Per-lead ceiling |
| --- | --- |
| Minimal reversible state change | 1 |
| Inert upload | 1 file, at most 1 KiB |
| Adjacent object identifiers after control | 3 |
| Credential guesses on one auth surface | 5 |
| OTP validation on a controlled identifier | 10, without extra sends |

## Platform-Specific Rules

- Platform profile: generic-vdp
- Additional rules: none recorded

## Scope Change Log

| Revision | Time | Source | Change | Affected leads |
| --- | --- | --- | --- | --- |
| 1 | 2026-01-01T00:00:00Z | initialization | Initial scope record | none |
