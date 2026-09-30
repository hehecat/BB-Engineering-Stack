# L4 Skills

`skills.yaml` is the single inventory. `library/` holds stack-owned routing
Skills; `vendor/community/` is the portable specialist snapshot. Installations
under Claude or Codex are links back to these sources, so there is one editable
copy.

For Bug Bounty, `bb-orchestrator` is the sole startup orchestrator. It owns the
Scope gate, soft Lead ranking, evidence grading, and root-cause clustering.
`bb-recon` owns deterministic baseline coverage, resume, adaptive branch state,
and explicit closure decisions; it does not choose the final hunting lead.
`bb-methodology` and broad reference Skills are loaded only when the active
queue needs them; specialist Skills are selected one Lead at a time.

For browser JavaScript analysis, `browser-js-orchestrator` owns the observe,
reconstruct, verify, and deliver loop. It does not preselect a vulnerability
class or output format; `ctf-web`, `api-security`, and `reverse-orchestrator`
remain optional Lead-specific routes.

For authorized non-BB assessment, `security-orchestrator` owns Scope, evidence,
cross-domain handoff, and checkpoints. Domain profiles route to Android, iOS,
network, cloud, LLM/agent, Web/API, or source specialists. Optional handoffs do
not replace the workflow orchestrator or import another Profile's policy.

```bash
bb-stack skills validate
bb-stack skills install --profile ctf-web --agent claude --required-only
bb-stack skills status --profile ctf-web --agent claude
bb-recon --help
```

An existing byte-identical Skill is accepted as `compatible-unmanaged`.
Different content is never replaced unless `--force` is supplied; replacement
first renames the old directory to a timestamped backup.

Before publishing the stack outside the operator's environment, review and
record upstream licenses and revisions for every `local-snapshot` entry.

`bb-stack updates check --skills` reports a digest for every Skill. Verified
GitHub-tree sources can use the staged update lifecycle; unknown snapshots stay
`manual` until repository, revision, path, and license provenance are recorded.

The iOS, network, cloud, SAST, IaC, container, SCA, and threat-model snapshots
are pinned to one recorded `ai-security-arsenal` revision and have GitHub-tree
update channels. Promotion still requires staged validation.

## Vendor provenance policy

Every entry in `skills.yaml` carries a `provenance`:

- `stack` — authored here, owned by this repository. No provenance record is
  required.
- anything else — a **vendored snapshot**: the directory was copied in from
  another project instead of being written here, including a copy taken from an
  operator's own machine.

A **named upstream** snapshot must record the upstream it came from.
`00-L0-Runtime/lib/bb_stack/skills.py` enforces this in `validate_all()`:
`bb-stack skills validate` (and `bb-stack validate`) fails with a
`ValidationError` naming the Skill when such an entry omits `repository` or
`revision`.

`local-snapshot` is the weak case, and it says exactly that: the files arrived
without a recorded repository, revision, or license. It is a placeholder, not a
licence to ship — the directory may be used inside a private runtime, and it
must not be redistributed or published until the license is verified against the
real upstream.

Recording a new vendored Skill:

1. Put the upstream files in `vendor/community/<name>/`.
2. Add the Skill to `skills.yaml` with `role`, `source`, `provenance`, and — for
   a named upstream — `repository`, `revision`, and `license`. Facts you do not
   have stay marked unknown — never guess a URL, revision, or license name.
3. For a pinned GitHub source, add the matching `skill.<name>` component to
   `00-L0-Runtime/config/upstreams.yaml` with `current_revision` and the
   `current_digest` computed by `SkillRegistry.tree_digest`.
4. Record `UPSTREAM.md` next to `SKILL.md` only when the snapshot carries local
   adaptations that the generic GitHub-tree updater would overwrite; that file
   then belongs to the pinned content and is not a substitute for the
   `skills.yaml` fields.

Any edit inside a vendored snapshot directory changes its tree digest. Update
`current_digest` in `00-L0-Runtime/config/upstreams.yaml` in the same change, or
`bb-stack validate` fails with `local digest drift`.

Current state: of the 47 vendored Skills, 10 have a recorded upstream (one
`ljagiello-ctf-skills` snapshot, eight pinned `ai-security-arsenal` snapshots,
and `android-reverse-engineering`); the other 37 are `local-snapshot` and remain
`needs-review`.
