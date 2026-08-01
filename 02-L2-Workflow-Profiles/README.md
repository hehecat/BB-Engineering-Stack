# L2 Workflow Profiles

Runtime profiles select exactly one workflow, platform overlay, mode, L4 Skill
profile, L5 capability profile, and Prompt mode.

| Runtime profile | Prompt | Workflow | Default use |
| --- | --- | --- | --- |
| `ctf-quick` | append | CTF | normal short challenge |
| `ctf-replacement` | replacement | CTF | explicit full replacement session |
| `ctf-android` | append | CTF + Android | APK static/dynamic analysis |
| `ctf-reverse` | append | CTF + Reverse | binary/artifact reverse engineering |
| `bb-interactive` | append | Bug Bounty | bounded operator task |
| `bb-continuous` | append | Bug Bounty | continuous hunt loop |
| `lab-replacement` | replacement | Lab | isolated fixture behavior |
| `browser-js` | append | Analysis + Browser JavaScript | runtime observation, reconstruction, and task-defined delivery |
| `analysis-android` | append | Analysis + Android | decompilation and behavior recovery without CTF policy |
| `analysis-reverse` | append | Analysis + Reverse | native/firmware behavior recovery without CTF policy |
| `assessment-web` | append | Assessment + Web/API | contracted or explicitly scoped application test |
| `assessment-android` | append | Assessment + Android | mobile application security test |
| `assessment-ios` | append | Assessment + iOS | IPA and device security test |
| `assessment-network` | append | Assessment + Network | network, service, and identity test |
| `assessment-cloud` | append | Assessment + Cloud | AWS/Azure/GCP posture and IAM test |
| `assessment-llm` | append | Assessment + LLM/Agent | model application and agent boundary test |
| `assessment-source` | append | Assessment + Source | SAST, IaC, container, SCA, and threat-model work |

Platform metadata is in `platforms/platforms.yaml`; model-facing differences are
in adjacent Markdown overlays. Add a platform once, then reference it from
profiles and Engagement state.

Profiles compose one workflow, one domain, and one platform; they do not inherit
another Profile. Cross-domain evidence may select an optional Skill without
changing the active workflow or platform overlay.
