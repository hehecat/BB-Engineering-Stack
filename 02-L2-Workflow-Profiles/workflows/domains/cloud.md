# Cloud Domain

Route through `security-orchestrator`, then use `cloud-security` for AWS, Azure,
or GCP identity, storage, network, secret, logging, federation, and privilege
path analysis. Record account, subscription or project, principal, regions,
credential source label, and read/write constraints before enumeration.

Prefer read-only inventory until a concrete lead requires a scoped validation.
Save normalized resource inventories and scanner output under
`artifacts/cloud/`, reusable queries under `scripts/`, and distinguish an
effective permission from a policy that merely appears to grant it.
