# L2 Workflow Profiles

Runtime profiles select exactly one workflow, platform overlay, mode, L4 Skill
profile, L5 capability profile, and Prompt mode.

| Runtime profile | Prompt | Workflow | Default use |
| --- | --- | --- | --- |
| `ctf-quick` | append | CTF | normal short challenge |
| `ctf-replacement` | replacement | CTF | explicit full replacement session |
| `bb-interactive` | append | Bug Bounty | bounded operator task |
| `bb-continuous` | append | Bug Bounty | continuous hunt loop |
| `lab-replacement` | replacement | Lab | isolated fixture behavior |

Platform metadata is in `platforms/platforms.yaml`; model-facing differences are
in adjacent Markdown overlays. Add a platform once, then reference it from
profiles and Engagement state.
