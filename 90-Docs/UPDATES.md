# Update Management

The update manager inventories every managed Skill, MCP package, and tool pin.
It never updates in the background and never promotes a candidate without an
explicit command.

## Check

```bash
bb-stack updates check --all
bb-stack updates check --skills
bb-stack updates check --mcp
bb-stack updates check --tools
bb-stack updates check --name skill.ctf-web
```

Important states:

| State | Meaning | Action |
| --- | --- | --- |
| `current` | The verified pin equals upstream | None |
| `update-available` | A different upstream version exists | Stage and validate |
| `manual` | Upstream or license is unverified | Record provenance before automation |
| `stack-owned` | Maintained in this repository | Update through normal review |
| `local-drift` | Files differ from the recorded digest | Review local changes first |
| `license-review` | Upstream license differs from the recorded license | Review before staging |
| `rate-limited` | A registry rejected an anonymous check | Set its optional token or retry later |
| `check-error` | One update channel failed | Retry it; other results remain valid |
| `system-managed` | The OS package manager owns the version | Use OS maintenance policy |

Large output belongs in a file:

```bash
bb-stack updates check --all --json > update-audit.json
```

## Candidate Lifecycle

```bash
bb-stack updates stage skill.ctf-web
bb-stack updates validate skill.ctf-web
bb-stack updates promote skill.ctf-web
bb-stack updates rollback skill.ctf-web
```

Candidates live under `.runtime/update-candidates`; promotion backups live
under `.runtime/update-backups`. Both are machine-local and ignored by Git.
Restaging preserves the preceding candidate with a timestamp instead of
deleting it.

GitHub tree checks compare only the registered Skill subdirectory. A commit to
another directory does not create an update. Git commit and release checks use
the Git transport; API-backed future channels may use `GITHUB_TOKEN` or
`GH_TOKEN` when present.

Automatic stage, validation, promotion, and rollback currently cover:

- GitHub-tree Skills: archive path validation, frontmatter validation, tree
  digest, registry contracts, and backup.
- npm MCP packages: lockfile integrity, isolated `npm ci`, real MCP initialize
  handshake, source contract validation, runtime rebuild, and backup.

Go, PyPI, Git data, release binaries/trees, pinned Debian packages, apt packages, services, and Keysmith are
checked but require a reviewed installer change before promotion. Checksums,
sparse data sets, system packages, and persistent Prompt deployment have
different rollback semantics.

## Add A Skill Source

1. Add the Skill to `04-L4-Skills/skills.yaml` and its profile.
2. Put the source under `library/` or `vendor/community/`.
3. If its repository, path, revision, and license are verified, add a
   `github-tree` component to `00-L0-Runtime/config/upstreams.yaml`.
4. Record the current tree digest from `bb-stack skills validate`.
5. Run `bb-stack validate`, `bb-stack updates check --skills`, and the full
   verification suite.

Without a verified upstream entry, the Skill remains usable and appears as
`manual`; it is not silently replaced.

## Add An MCP

1. Pin the npm package in the Node runtime `package.json` and lockfile.
2. Add one provider with a globally unique `mcp.name`.
3. Map it to a capability and profile.
4. Add one npm component with the matching provider in `upstreams.yaml`.
5. Run schema validation, isolated MCP probe, Doctor, and fresh-machine tests.

Duplicate YAML keys, duplicate upstream targets, missing MCP update entries,
and duplicate MCP server names are contract failures.
