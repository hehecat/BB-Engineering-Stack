from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import urlparse

from .errors import StackError, ValidationError
from .io import dump_yaml, load_yaml
from .paths import StackPaths
from .validation import validate


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKFLOW_PHASE = {"bug-bounty": "explore", "ctf": "triage", "lab": "reproduce"}
WORKFLOW_PLATFORM = {
    "bug-bounty": "generic-vdp",
    "ctf": "standalone-ctf",
    "lab": "local-lab",
}
TRANSITIONS = {
    "active": {"paused", "blocked", "closed"},
    "paused": {"active", "closed"},
    "blocked": {"active", "closed"},
    "closed": {"active"},
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def infer_asset(target: str) -> dict[str, str]:
    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        if not parsed.hostname:
            raise ValidationError(f"invalid target URL: {target}")
        return {"type": "url-prefix", "pattern": target.rstrip("/")}
    try:
        ipaddress.ip_network(target, strict=False)
        return {"type": "cidr" if "/" in target else "host", "pattern": target}
    except ValueError:
        pass
    if target.startswith(("./", "../", "/", "~/")) or Path(target).suffix:
        return {"type": "other", "pattern": target}
    return {"type": "host", "pattern": target}


class EngagementManager:
    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.layer = paths.root / "03-L3-Engagement-State"
        self.schema = self.layer / "schema" / "engagement.schema.json"
        self.templates = self.layer / "templates"
        self.platform_registry = load_yaml(
            paths.root / "02-L2-Workflow-Profiles" / "platforms" / "platforms.yaml"
        )["platforms"]

    def create(
        self,
        slug: str,
        target: str,
        *,
        workflow: str,
        platform: str | None = None,
        mode: str = "interactive",
        title: str | None = None,
        authorization_source: str | None = None,
        route_kind: str | None = None,
    ) -> Path:
        if not SLUG_RE.fullmatch(slug):
            raise ValidationError("slug must use lowercase letters, digits, and single hyphens")
        if workflow not in WORKFLOW_PHASE:
            raise ValidationError(f"unsupported workflow: {workflow}")
        if mode not in {"interactive", "continuous"}:
            raise ValidationError(f"unsupported mode: {mode}")
        root = (self.paths.engagements_root / slug).resolve()
        try:
            root.relative_to(self.paths.engagements_root.resolve())
        except ValueError as error:
            raise ValidationError("engagement path escapes the workspace engagements directory") from error
        if root.exists():
            raise StackError(f"engagement already exists: {root}")

        timestamp = now()
        platform = platform or WORKFLOW_PLATFORM[workflow]
        if platform not in self.platform_registry:
            raise ValidationError(f"unknown platform: {platform}")
        platform_contract = self.platform_registry[platform]
        if workflow not in platform_contract["workflows"]:
            raise ValidationError(f"platform {platform} does not support workflow {workflow}")
        asset = infer_asset(target)
        authorization_status = "confirmed" if workflow == "bug-bounty" else "not-required"
        authorization_source = authorization_source or (
            "User instruction and written program rules captured in notes/SCOPE.md"
            if workflow == "bug-bounty"
            else "Competition challenge statement or local fixture captured in notes/SCOPE.md"
        )
        state: dict[str, Any] = {
            "schema_version": 1,
            "slug": slug,
            "title": title or self._default_title(workflow, slug),
            "workflow": workflow,
            "platform": platform,
            "mode": mode,
            "lifecycle": "active",
            "phase": WORKFLOW_PHASE[workflow],
            "timestamps": {"created_at": timestamp, "updated_at": timestamp},
            "authorization": {
                "status": authorization_status,
                "source": authorization_source,
            },
            "scope": {
                "file": "notes/SCOPE.md",
                "revision": 1,
                "reviewed_at": timestamp,
                "in_scope": [asset],
                "out_of_scope": [],
            },
            "overlays": {"delivery": [platform_contract["delivery_overlay"]]},
            "identity": {
                "request_identification": {
                    "enabled": platform_contract["request_identification"] == "required",
                    "value_from": platform_contract["identity_value_from"],
                },
                "contexts": [],
            },
            "current": {
                "lead_id": None,
                "finding_id": None,
                "next_action": self._first_action(workflow),
                "stop_reason": None,
            },
            "checkpoint": {"handoff_file": "SESSION-HANDOFF.md", "updated_at": timestamp},
        }
        if route_kind is not None:
            state["routing"] = {"kind": route_kind}
        validate(state, self.schema, "new engagement")

        self._make_directories(root, workflow)
        dump_yaml(root / "engagement.yaml", state)
        self._write_control_files(root, state, target, timestamp)
        self.validate(root)
        return root

    @staticmethod
    def _default_title(workflow: str, slug: str) -> str:
        prefix = {"bug-bounty": "Bug Bounty", "ctf": "CTF", "lab": "Lab"}[workflow]
        return f"{prefix}: {slug}"

    @staticmethod
    def _first_action(workflow: str) -> str:
        return {
            "bug-bounty": "Read notes/SCOPE.md and select the first in-scope lead",
            "ctf": "Read the challenge statement, inventory artifacts, and classify the solve path",
            "lab": "Read notes/SCOPE.md and reproduce the supplied behavior",
        }[workflow]

    def _make_directories(self, root: Path, workflow: str) -> None:
        common = ["notes", "artifacts", "scripts", "reports", "deliverables"]
        specific = {
            "bug-bounty": ["recon/findings", "recon/js", "h1-packages", "lab"],
            "ctf": ["challenge", "artifacts/http", "artifacts/browser"],
            "lab": ["fixture", "artifacts/logs", "artifacts/browser"],
        }[workflow]
        for relative in common + specific:
            (root / relative).mkdir(parents=True, exist_ok=True)

    def _write_control_files(
        self, root: Path, state: dict[str, Any], target: str, timestamp: str
    ) -> None:
        workflow = state["workflow"]
        (root / ".gitignore").write_text(
            (self.templates / ".gitignore").read_text(encoding="utf-8")
            + ".bb-stack/\n",
            encoding="utf-8",
        )
        (root / "CLAUDE.md").write_text(
            "# Active Security Work Unit\n\n"
            "Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and "
            "`STATUS.md` before acting. Keep evidence and generated output in this work "
            "unit. Never put credentials or complete tokens in Prompt, reports, shared "
            "artifacts, or version control.\n",
            encoding="utf-8",
        )
        (root / "notes" / "SCOPE.md").write_text(
            self._scope_markdown(state, target, timestamp), encoding="utf-8"
        )
        (root / "STATUS.md").write_text(
            self._status_markdown(state, timestamp), encoding="utf-8"
        )
        (root / "SESSION-HANDOFF.md").write_text(
            self._handoff_markdown(state, timestamp), encoding="utf-8"
        )
        if workflow == "bug-bounty":
            for name in ("hypotheses.md",):
                shutil.copy2(self.templates / name, root / name)
            shutil.copy2(self.templates / "notes" / "findings-live.md", root / "notes" / "findings-live.md")
        elif workflow == "ctf":
            (root / "notes" / "solve-log.md").write_text(
                "# Solve Log\n\n| Time | Observation | Hypothesis | Evidence | Next action |\n"
                "| --- | --- | --- | --- | --- |\n",
                encoding="utf-8",
            )
        else:
            (root / "notes" / "experiment-log.md").write_text(
                "# Experiment Log\n\n| Time | Baseline | Change | Result | Evidence | Conclusion |\n"
                "| --- | --- | --- | --- | --- | --- |\n",
                encoding="utf-8",
            )
        credential_template = self.templates / "notes" / "LAB-CREDS.local.md.example"
        shutil.copy2(credential_template, root / "notes" / credential_template.name)

    @staticmethod
    def _scope_markdown(state: dict[str, Any], target: str, timestamp: str) -> str:
        return (
            "# Scope And Rules\n\n"
            f"Reviewed: {timestamp}\n"
            "Revision: 1\n\n"
            "## Authorization Source\n\n"
            f"- Status: {state['authorization']['status']}\n"
            f"- Source: {state['authorization']['source']}\n"
            f"- Workflow: {state['workflow']}\n"
            f"- Platform: {state['platform']}\n\n"
            "## In-Scope Assets\n\n"
            "| Asset or pattern | Type | Conditions |\n"
            "| --- | --- | --- |\n"
            f"| `{target}` | {state['scope']['in_scope'][0]['type']} | Initial supplied target |\n\n"
            "## Out-Of-Scope Assets\n\nNone recorded.\n\n"
            "## Operating Rules\n\n"
            "- Record current rate, identity, side-effect, and disclosure rules before testing.\n"
            "- Keep requests inside the assets and conditions above.\n"
            "- Preserve exact evidence paths and redact secrets from shareable output.\n"
        )

    @staticmethod
    def _status_markdown(state: dict[str, Any], timestamp: str) -> str:
        return (
            "# Status\n\n"
            f"Last checkpoint: {timestamp}\n\n"
            "## Control Snapshot\n\n"
            "| Field | Value |\n| --- | --- |\n"
            f"| Lifecycle | {state['lifecycle']} |\n"
            f"| Mode | {state['mode']} |\n"
            f"| Phase | {state['phase']} |\n"
            "| Scope revision | 1 |\n"
            "| Current lead | none |\n"
            "| Current finding | none |\n\n"
            "## Current Objective\n\nEstablish the first reproducible lead.\n\n"
            f"## Exact Next Action\n\n{state['current']['next_action']}.\n\n"
            "## Queue\n\n| Priority | ID | Surface | Signal | Next test |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 1 | none | Initial target | Not inventoried | Inventory supplied surface |\n\n"
            "## Blockers\n\nNone.\n"
        )

    @staticmethod
    def _handoff_markdown(state: dict[str, Any], timestamp: str) -> str:
        return (
            "# Session Handoff\n\n"
            f"Updated: {timestamp}\n\n"
            "## Resume Order\n\n"
            "1. Read `engagement.yaml` and `notes/SCOPE.md`.\n"
            "2. Read this handoff and `STATUS.md`.\n"
            "3. Open referenced evidence and execute the exact next action.\n\n"
            "## Current State\n\n"
            f"- Lifecycle: {state['lifecycle']}\n"
            f"- Mode: {state['mode']}\n"
            f"- Phase: {state['phase']}\n"
            "- Scope revision: 1\n"
            "- Current lead: none\n"
            "- Current finding: none\n\n"
            "## Established Facts\n\n- Work unit initialized; no technical conclusion yet.\n\n"
            "## Evidence To Open\n\nNo evidence files yet.\n\n"
            "## Exact Next Actions\n\n"
            f"1. {state['current']['next_action']}.\n\n"
            "## External Dependency\n\nNone.\n"
        )

    def validate(self, root: Path) -> dict[str, Any]:
        root = root.expanduser().resolve()
        state_path = root / "engagement.yaml"
        if not state_path.is_file():
            raise ValidationError(f"missing engagement.yaml: {root}")
        state = load_yaml(state_path)
        validate(state, self.schema, f"engagement {root.name}")
        if state["slug"] != root.name:
            raise ValidationError(
                f"engagement slug/path mismatch: {state['slug']} != {root.name}"
            )
        required = ["notes/SCOPE.md", "STATUS.md", "SESSION-HANDOFF.md", "CLAUDE.md"]
        for relative in required:
            if not (root / relative).is_file():
                raise ValidationError(f"missing engagement control file: {relative}")
        credentials = root / "notes" / "LAB-CREDS.local.md"
        if credentials.exists() and credentials.stat().st_mode & 0o077:
            raise ValidationError(f"credential file permissions must be 600 or stricter: {credentials}")
        return state

    def list(self) -> list[dict[str, str]]:
        result = []
        for path in self.roots():
            if not (path / "engagement.yaml").is_file():
                continue
            try:
                state = self.validate(path)
                result.append(
                    {
                        "slug": state["slug"],
                        "workflow": state["workflow"],
                        "lifecycle": state["lifecycle"],
                        "phase": state["phase"],
                        "path": str(path),
                    }
                )
            except ValidationError as error:
                result.append({"slug": path.name, "error": str(error), "path": str(path)})
        return result

    def roots(self) -> list[Path]:
        roots: list[Path] = []
        if self.paths.engagements_root.is_dir():
            roots.extend(
                path
                for path in sorted(self.paths.engagements_root.iterdir())
                if path.is_dir()
            )
        # Read-only compatibility for work units created before the workspace
        # gained an explicit engagements/ boundary.
        if self.paths.work_root.is_dir():
            roots.extend(
                path
                for path in sorted(self.paths.work_root.iterdir())
                if path.is_dir()
                and path != self.paths.engagements_root
                and (path / "engagement.yaml").is_file()
            )
        return roots

    def transition(self, root: Path, lifecycle: str, reason: str | None = None) -> dict[str, Any]:
        state = self.validate(root)
        current = state["lifecycle"]
        if lifecycle == current:
            return state
        if lifecycle not in TRANSITIONS.get(current, set()):
            raise ValidationError(f"invalid lifecycle transition: {current} -> {lifecycle}")
        timestamp = now()
        state["lifecycle"] = lifecycle
        state["timestamps"]["updated_at"] = timestamp
        state["checkpoint"]["updated_at"] = timestamp
        state["current"]["stop_reason"] = reason if lifecycle in {"paused", "blocked", "closed"} else None
        dump_yaml(root / "engagement.yaml", state)
        return state

    def checkpoint(self, root: Path) -> dict[str, Any]:
        state = self.validate(root)
        timestamp = now()
        state["timestamps"]["updated_at"] = timestamp
        state["checkpoint"]["updated_at"] = timestamp
        dump_yaml(root / "engagement.yaml", state)
        return state

    def migrate_legacy(
        self,
        source: Path,
        slug: str,
        target: str,
        *,
        workflow: str,
        platform: str | None,
        yes: bool,
    ) -> Path:
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise ValidationError(f"legacy source is not a directory: {source}")
        destination = self.paths.engagements_root / slug
        if not yes:
            return destination
        created = self.create(
            slug,
            target,
            workflow=workflow,
            platform=platform,
            title=f"Migrated: {slug}",
        )
        legacy = created / "legacy-import"
        shutil.copytree(
            source,
            legacy,
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", ".venv", "*.jwt", "*.cookie", "cookies.txt"
            ),
        )
        return created
