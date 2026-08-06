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
