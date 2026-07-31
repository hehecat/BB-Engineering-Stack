# Upstream

- Repository: `https://github.com/SimoneAvogadro/android-reverse-engineering-skill`
- Revision: `e8dde9d058badbd5a62265d5d23e81f0ea8f04dd`
- License: Apache-2.0 (`LICENSE`)
- Snapshot path: `plugins/android-reverse-engineering/skills/android-reverse-engineering`

Stack adaptations:

- Added the `name` frontmatter required by the L4 registry.
- Replaced `CLAUDE_PLUGIN_ROOT` references with the portable `BB_STACK_ROOT`.
- Routed dependency installation through `bb-stack bootstrap --profile android`.

Upstream updates require a reviewed snapshot refresh because these adaptations
are intentionally not applied by the generic GitHub-tree updater.
