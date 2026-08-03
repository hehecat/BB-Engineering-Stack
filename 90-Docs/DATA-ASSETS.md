# Data Assets

Use the data manager for SecLists, PayloadsAllTheThings, and Trickest wordlists.
Each source is pinned to one reviewed Git commit. Each functional bundle has
sentinel files, so a repository directory alone never counts as complete.

## Inspect

```bash
bb-stack data status --profile web
bb-stack data status seclists
bb-stack data path payloads-all-the-things
bb-stack data update --check
```

Interpret dataset states as follows:

| State | Required action |
| --- | --- |
| `missing` | Install the required bundle. |
| `partial` | Install the reported missing bundle. |
| `stale` | Reinstall at the catalog revision. |
| `incompatible` | Move or inspect the unmanaged destination; never overwrite it automatically. |
| `ready` | Use the resolved path. |

## Install

```bash
bb-stack data ensure --profile web
bb-stack data ensure --profile ctf-web --with-optional
bb-stack data ensure seclists --bundle dns
bb-stack data ensure seclists --bundle complete
bb-stack data ensure payloads-all-the-things --bundle web-core
bb-stack data ensure trickest-wordlists --bundle recon
```

Bootstrap installs the selected Profile's required bundles unless
`--skip-tools` is set. Strict launch checks again and downloads a missing
required bundle before capability Doctor runs. Optional and complete bundles
remain explicit.

## Preserve Integrity

- Keep destinations below `$BB_DATA_ROOT`.
- Keep repository URLs and 40-character revisions in `data-catalog.yaml`.
- Add one or more stable file sentinels for every bundle.
- Run `bb-stack data update --check`; do not move pins in the background.
- Review a new upstream revision and its sentinel paths before changing a pin.
- Run `test_data.py`, `bb-stack validate`, and the full verification suite.

Installations use a per-dataset file lock, a fresh staged checkout, and atomic
directory replacement. A failed download or validation leaves the preceding
managed checkout in place. Additional sparse bundles are unioned with the
already installed paths; `complete` disables sparse checkout and retrieves the
whole repository.
