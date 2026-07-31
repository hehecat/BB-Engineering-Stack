# L4 Skills

`skills.yaml` is the single inventory. `library/` holds stack-owned routing
Skills; `vendor/community/` is the portable specialist snapshot. Installations
under Claude or Codex are links back to these sources, so there is one editable
copy.

```bash
bb-stack skills validate
bb-stack skills install --profile ctf-web --agent claude --required-only
bb-stack skills status --profile ctf-web --agent claude
```

An existing byte-identical Skill is accepted as `compatible-unmanaged`.
Different content is never replaced unless `--force` is supplied; replacement
first renames the old directory to a timestamped backup.

Before publishing the stack outside the operator's environment, review and
record upstream licenses and revisions for every `local-snapshot` entry.

`bb-stack updates check --skills` reports a digest for every Skill. Verified
GitHub-tree sources can use the staged update lifecycle; unknown snapshots stay
`manual` until repository, revision, path, and license provenance are recorded.
