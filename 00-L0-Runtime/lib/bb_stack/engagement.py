from __future__ import annotations

import ipaddress
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunsplit

from .errors import StackError, ValidationError
from .io import atomic_write, dump_json, dump_yaml, load_yaml
from .paths import StackPaths
from .validation import validate

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKFLOW_PHASE = {
    "bug-bounty": "explore",
    "assessment": "scope",
    "ctf": "triage",
    "lab": "reproduce",
    "analysis": "inspect",
}
WORKFLOW_PLATFORM = {
    "bug-bounty": "generic-vdp",
    "assessment": "authorized-assessment",
    "ctf": "standalone-ctf",
    "lab": "local-lab",
    "analysis": "standalone-analysis",
}
TRANSITIONS = {
    "active": {"paused", "blocked", "closed"},
    "paused": {"active", "closed"},
    "blocked": {"active", "closed"},
    "closed": {"active"},
}
PROTECTED_WORKFLOWS = {"bug-bounty", "assessment"}
AUTHORIZATION_STATUSES = {"pending", "user-asserted", "verified", "exempt", "revoked"}
# Statuses that permit active target traffic for protected workflows.
AUTHORIZED_STATUSES = {"verified", "user-asserted"}


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validated_text(value: str, label: str) -> str:
    if not value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValidationError(f"{label} contains empty or control characters")
    return value


def _markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")


def normalize_target(target: str) -> tuple[dict[str, str], str | None]:
    target = _validated_text(target, "target")
    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        if not parsed.hostname:
            raise ValidationError(f"invalid target URL: {target}")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValidationError(f"invalid target URL port: {target}") from error
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        netloc = host if port is None else f"{host}:{port}"
        public_target = urlunsplit(
            (parsed.scheme.lower(), netloc, parsed.path or "/", "", "")
        )
        sensitive_target = target if target != public_target else None
        return {"type": "url-prefix", "pattern": public_target}, sensitive_target
    try:
        ipaddress.ip_network(target, strict=False)
        return {"type": "cidr" if "/" in target else "host", "pattern": target}, None
    except ValueError:
        pass
    if target.startswith(("./", "../", "/", "~/")) or Path(target).suffix:
        return {"type": "other", "pattern": target}, None
    return {"type": "host", "pattern": target}, None


def infer_asset(target: str) -> dict[str, str]:
    return normalize_target(target)[0]


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
        authorization_status: str | None = None,
        route_kind: str | None = None,
    ) -> Path:
        if not SLUG_RE.fullmatch(slug):
            raise ValidationError(
                "slug must use lowercase letters, digits, and single hyphens"
            )
        if workflow not in WORKFLOW_PHASE:
            raise ValidationError(f"unsupported workflow: {workflow}")
        if mode not in {"interactive", "continuous"}:
            raise ValidationError(f"unsupported mode: {mode}")
        root = (self.paths.engagements_root / slug).resolve()
        try:
            root.relative_to(self.paths.engagements_root.resolve())
        except ValueError as error:
            raise ValidationError(
                "engagement path escapes the workspace engagements directory"
            ) from error
        if root.exists():
            raise StackError(f"engagement already exists: {root}")

        timestamp = now()
        platform = platform or WORKFLOW_PLATFORM[workflow]
        if platform not in self.platform_registry:
            raise ValidationError(f"unknown platform: {platform}")
        platform_contract = self.platform_registry[platform]
        if workflow not in platform_contract["workflows"]:
            raise ValidationError(
                f"platform {platform} does not support workflow {workflow}"
            )
        asset, sensitive_target = normalize_target(target)
        authorization_source = (
            _validated_text(authorization_source, "authorization source")
            if authorization_source
            else None
        )
        if workflow in PROTECTED_WORKFLOWS:
            authorization_status = authorization_status or (
                "user-asserted" if authorization_source else "pending"
            )
            if authorization_status not in {"pending", "user-asserted", "verified"}:
                raise ValidationError(
                    "protected workflows require pending, user-asserted, or verified authorization"
                )
            if (
                authorization_status in {"user-asserted", "verified"}
                and not authorization_source
            ):
                raise ValidationError(
                    f"authorization source is required for status {authorization_status}"
                )
        else:
            if authorization_status not in {None, "exempt"}:
                raise ValidationError(
                    f"workflow {workflow} uses exempt authorization status"
                )
            authorization_status = "exempt"
            authorization_source = authorization_source or (
                "User-supplied analysis input and requested outcome"
                if workflow == "analysis"
                else "Competition challenge or local fixture"
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
                "candidates": [],
                "out_of_scope": [],
            },
            "overlays": {"delivery": [platform_contract["delivery_overlay"]]},
            "identity": {
                "request_identification": {
                    "enabled": platform_contract["request_identification"]
                    == "required",
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
            "checkpoint": {
                "handoff_file": "SESSION-HANDOFF.md",
                "updated_at": timestamp,
            },
        }
        if sensitive_target:
            state["scope"]["sensitive_target_ref"] = "notes/TARGET.local.json"
        if workflow in PROTECTED_WORKFLOWS and authorization_status not in AUTHORIZED_STATUSES:
            state["current"]["next_action"] = (
                "Record and verify the authorization basis (user statement or written "
                "source) in notes/SCOPE.md before active testing"
            )
        if route_kind is not None:
            state["routing"] = {"kind": route_kind}
        validate(state, self.schema, "new engagement")

        self._make_directories(root, workflow)
        dump_yaml(root / "engagement.yaml", state)
        self._write_control_files(
            root,
            state,
            asset["pattern"],
            timestamp,
            sensitive_target=sensitive_target,
        )
        self.validate(root)
        return root

    @staticmethod
    def _default_title(workflow: str, slug: str) -> str:
        prefix = {
            "bug-bounty": "Bug Bounty",
            "assessment": "Security Assessment",
            "ctf": "CTF",
            "lab": "Lab",
            "analysis": "Security Analysis",
        }[workflow]
        return f"{prefix}: {slug}"

    @staticmethod
    def _first_action(workflow: str) -> str:
        return {
            "bug-bounty": "Read notes/SCOPE.md and select the first in-scope lead",
            "assessment": "Read notes/SCOPE.md and select the first scoped assessment lead",
            "ctf": "Read the challenge statement, inventory artifacts, and classify the solve path",
            "lab": "Read notes/SCOPE.md and reproduce the supplied behavior",
            "analysis": "Inventory the supplied input and identify the smallest relevant behavior or call chain",
        }[workflow]

    def _make_directories(self, root: Path, workflow: str) -> None:
        common = ["notes", "artifacts", "scripts", "reports", "deliverables"]
        specific = {
            "bug-bounty": ["recon/findings", "recon/js", "h1-packages", "lab"],
            "assessment": ["artifacts/evidence"],
            "ctf": ["challenge", "artifacts/http", "artifacts/browser"],
            "lab": ["fixture", "artifacts/logs", "artifacts/browser"],
            "analysis": [
                "input",
                "artifacts/browser",
                "artifacts/network",
                "artifacts/javascript",
            ],
        }[workflow]
        for relative in common + specific:
            (root / relative).mkdir(parents=True, exist_ok=True)

    def _write_control_files(
        self,
        root: Path,
        state: dict[str, Any],
        target: str,
        timestamp: str,
        *,
        sensitive_target: str | None = None,
    ) -> None:
        workflow = state["workflow"]
        (root / ".gitignore").write_text(
            (self.templates / ".gitignore").read_text(encoding="utf-8")
            + ".bb-stack/\n",
            encoding="utf-8",
        )
        boundary_rule = (
            "Discovered adjacent assets remain candidates until written Scope promotes them. "
            if workflow in {"bug-bounty", "assessment"}
            else "Keep work within the supplied challenge, fixture, or analysis boundary. "
        )
        findings_rule = (
            "Bug Bounty findings use `notes/findings-live.md`; do not create a parallel "
            "findings log.\n"
            if workflow in {"bug-bounty", "assessment"}
            else "Use the workflow-specific log under `notes/`.\n"
        )
        authorization_rule = (
            "For this protected workflow, active target traffic requires the current "
            "lifecycle to be `active` and `authorization.status` to be `verified` or "
            "`user-asserted`, with the basis recorded in `notes/SCOPE.md` exactly as "
            "the user states it (own asset, provided artifact, or named program). "
            "`pending` or `revoked` stops active testing; never invent a basis or infer "
            "one from access, credentials, or ownership. "
            if workflow in PROTECTED_WORKFLOWS
            else "This workflow uses exempt authorization; do not request an authorization "
            "change unless the work is rerouted to a protected workflow. "
        )
        (root / "CLAUDE.md").write_text(
            "# Active Work Unit\n\n"
            "Read `engagement.yaml`, `notes/SCOPE.md`, `SESSION-HANDOFF.md`, and "
            "`STATUS.md` before acting. Act only while the current lifecycle is `active`; "
            "a paused, blocked, or closed lifecycle stops execution. "
            + authorization_rule
            + "Keep evidence and generated output in this work unit. Never put credentials "
            "or complete tokens in Prompt, reports, shared artifacts, or version control. "
            + boundary_rule
            + findings_rule,
            encoding="utf-8",
        )
        (root / "notes" / "SCOPE.md").write_text(
            self._scope_markdown(state, target, timestamp), encoding="utf-8"
        )
        if sensitive_target:
            dump_json(
                root / "notes" / "TARGET.local.json",
                {"target": sensitive_target},
                mode=0o600,
            )
        (root / "STATUS.md").write_text(
            self._status_markdown(state, timestamp), encoding="utf-8"
        )
        (root / "SESSION-HANDOFF.md").write_text(
            self._handoff_markdown(state, timestamp), encoding="utf-8"
        )
        if workflow in {"bug-bounty", "assessment"}:
            for name in ("hypotheses.md",):
                shutil.copy2(self.templates / name, root / name)
            shutil.copy2(
                self.templates / "notes" / "findings-live.md",
                root / "notes" / "findings-live.md",
            )
        elif workflow == "ctf":
            (root / "notes" / "solve-log.md").write_text(
                "# Solve Log\n\n| Time | Observation | Hypothesis | Evidence | Next action |\n"
                "| --- | --- | --- | --- | --- |\n",
                encoding="utf-8",
            )
        elif workflow == "lab":
            (root / "notes" / "experiment-log.md").write_text(
                "# Experiment Log\n\n| Time | Baseline | Change | Result | Evidence | Conclusion |\n"
                "| --- | --- | --- | --- | --- | --- |\n",
                encoding="utf-8",
            )
        else:
            (root / "notes" / "analysis-log.md").write_text(
                "# Analysis Log\n\n"
                "| Time | Runtime observation | Static lead | Experiment | Evidence | Next action |\n"
                "| --- | --- | --- | --- | --- | --- |\n",
                encoding="utf-8",
            )
        credential_template = self.templates / "notes" / "LAB-CREDS.local.md.example"
        shutil.copy2(credential_template, root / "notes" / credential_template.name)

    @staticmethod
    def _scope_markdown(state: dict[str, Any], target: str, timestamp: str) -> str:
        visible_target = _markdown_text(target)
        authorization_source = state["authorization"]["source"] or "Not supplied"
        visible_source = _markdown_text(authorization_source)
        revision = state["scope"]["revision"]
        if state["workflow"] == "analysis":
            return (
                "# Analysis Boundary And Outcome\n\n"
                f"Reviewed: {timestamp}\n"
                f"Revision: {revision}\n\n"
                "## Supplied Input\n\n"
                "| Input | Type | Conditions |\n"
                "| --- | --- | --- |\n"
                f"| `{visible_target}` | {state['scope']['in_scope'][0]['type']} | Initial supplied target |\n\n"
                "## Requested Outcome\n\n"
                "Record the requested behavior, acceptance criteria, and preferred integration "
                "surface here as they become known. The output format is not predetermined.\n\n"
                "## Operating Rules\n\n"
                "- Preserve original files and captured baselines.\n"
                "- Treat scripts and subresources loaded by the supplied page as analysis inputs, "
                "not as independent security-test targets.\n"
                "- Keep exact evidence paths and separate observed, inferred, and verified claims.\n"
            )
        content = (
            "# Scope And Rules\n\n"
            f"Reviewed: {timestamp}\n"
            f"Revision: {revision}\n\n"
            "## Authorization Source\n\n"
            f"- Status: {state['authorization']['status']}\n"
            f"- Source: {visible_source}\n"
            f"- Workflow: {state['workflow']}\n"
            f"- Platform: {state['platform']}\n\n"
            "## In-Scope Assets\n\n"
            "| Asset or pattern | Type | Conditions |\n"
            "| --- | --- | --- |\n"
            f"| `{visible_target}` | {state['scope']['in_scope'][0]['type']} | Initial supplied target |\n\n"
            "## Out-Of-Scope Assets\n\nNone recorded.\n\n"
            "## Candidate Assets\n\n"
            "Discovered relationship is not authorization. Record provenance here and "
            "promote an asset only with a written source and Scope revision.\n\n"
            "| Asset or pattern | Type | Provenance | Active testing |\n"
            "| --- | --- | --- | --- |\n"
            "| None recorded | other | none | prohibited until promoted |\n\n"
            "## Operating Rules\n\n"
            "- Record current rate, identity, side-effect, and disclosure rules before testing.\n"
            "- Keep requests inside the assets and conditions above.\n"
            "- Preserve exact evidence paths and redact secrets from shareable output.\n\n"
        )
        if state["workflow"] != "bug-bounty":
            return content
        return content + (
            "## Default Production Action Budget\n\n"
            "Written program rules and explicit Scope revisions override these defaults.\n\n"
            "| Action | Per-lead ceiling |\n"
            "| --- | --- |\n"
            "| Minimal reversible state change | 1 |\n"
            "| Inert upload | 1 file, at most 1 KiB |\n"
            "| Adjacent object identifiers after control | 3 |\n"
            "| Credential guesses on one auth surface | 5 |\n"
            "| OTP validation on a controlled identifier | 10, without extra sends |\n"
        )

    @staticmethod
    def _status_markdown(state: dict[str, Any], timestamp: str) -> str:
        protected_pending = bool(
            state["workflow"] in PROTECTED_WORKFLOWS
            and state["authorization"]["status"] == "pending"
        )
        scope_section = (
            "## Scope Candidates\n\nNone recorded. Candidate assets are not active "
            "targets until a Scope revision records their authorization source.\n\n"
            if state["workflow"] in {"bug-bounty", "assessment"}
            else ""
        )
        objective = state["current"]["next_action"]
        blocker = (
            "Authorization is revoked; active testing is prohibited."
            if state["authorization"]["status"] == "revoked"
            else (
                "Authorization basis is pending; record the user statement or "
                "written source before active testing."
                if protected_pending
                else "None."
            )
        )
        initial_surface = (
            "Supplied input | Not observed | Inventory and capture a baseline"
            if state["workflow"] == "analysis"
            else "Initial target | Not inventoried | Inventory supplied surface"
        )
        prefix = (
            "# Status\n\n"
            f"Last checkpoint: {timestamp}\n\n"
            "## Control Snapshot\n\n"
            "| Field | Value |\n| --- | --- |\n"
            f"| Lifecycle | {state['lifecycle']} |\n"
            f"| Authorization | {state['authorization']['status']} |\n"
            f"| Mode | {state['mode']} |\n"
            f"| Phase | {state['phase']} |\n"
            f"| Scope revision | {state['scope']['revision']} |\n"
            "| Current lead | none |\n"
            "| Current finding | none |\n\n"
            f"## Current Objective\n\n{objective}\n\n"
        )
        return (
            prefix
            + scope_section
            + (
                f"## Exact Next Action\n\n{state['current']['next_action']}.\n\n"
                "## Queue\n\n| Priority | ID | Surface | Signal | Next test |\n"
                "| --- | --- | --- | --- | --- |\n"
                f"| 1 | none | {initial_surface} |\n\n"
                f"## Blockers\n\n{blocker}\n"
            )
        )

    @staticmethod
    def _handoff_markdown(state: dict[str, Any], timestamp: str) -> str:
        protected_pending = bool(
            state["workflow"] in PROTECTED_WORKFLOWS
            and state["authorization"]["status"] == "pending"
        )
        external_dependency = (
            "Renewed written authorization and verification."
            if state["authorization"]["status"] == "revoked"
            else (
                "Recorded authorization basis (user statement or written source)."
                if protected_pending
                else "None."
            )
        )
        scope_section = (
            "## Scope Candidates\n\nNone recorded. Do not actively test discovered adjacent "
            "assets unless the written Scope has promoted them.\n\n"
            if state["workflow"] in {"bug-bounty", "assessment"}
            else ""
        )
        prefix = (
            "# Session Handoff\n\n"
            f"Updated: {timestamp}\n\n"
            "## Resume Order\n\n"
            "1. Read `engagement.yaml` and `notes/SCOPE.md`.\n"
            "2. Read this handoff and `STATUS.md`.\n"
            "3. Open referenced evidence and execute the exact next action.\n\n"
            "## Current State\n\n"
            f"- Lifecycle: {state['lifecycle']}\n"
            f"- Authorization: {state['authorization']['status']}\n"
            f"- Mode: {state['mode']}\n"
            f"- Phase: {state['phase']}\n"
            f"- Scope revision: {state['scope']['revision']}\n"
            "- Current lead: none\n"
            "- Current finding: none\n\n"
            "## Established Facts\n\n- Work unit initialized; no technical conclusion yet.\n\n"
        )
        return (
            prefix
            + scope_section
            + (
                "## Evidence To Open\n\nNo evidence files yet.\n\n"
                "## Exact Next Actions\n\n"
                f"1. {state['current']['next_action']}.\n\n"
                f"## External Dependency\n\n{external_dependency}\n"
            )
        )

    @staticmethod
    def _sync_control_snapshots(root: Path, state: dict[str, Any]) -> None:
        status_path = root / "STATUS.md"
        status = status_path.read_text(encoding="utf-8")
        status = re.sub(
            r"^\| Lifecycle \| .+ \|$",
            lambda _: f"| Lifecycle | {state['lifecycle']} |",
            status,
            count=1,
            flags=re.MULTILINE,
        )
        if "| Authorization |" not in status:
            lifecycle_line = f"| Lifecycle | {state['lifecycle']} |\n"
            status = status.replace(
                lifecycle_line,
                lifecycle_line
                + f"| Authorization | {state['authorization']['status']} |\n",
                1,
            )
        status = re.sub(
            r"^\| Authorization \| .+ \|$",
            lambda _: f"| Authorization | {state['authorization']['status']} |",
            status,
            count=1,
            flags=re.MULTILINE,
        )
        status = re.sub(
            r"^\| Scope revision \| [0-9]+ \|$",
            lambda _: f"| Scope revision | {state['scope']['revision']} |",
            status,
            count=1,
            flags=re.MULTILINE,
        )
        status = re.sub(
            r"^## Exact Next Action\n\n.+$",
            lambda _: f"## Exact Next Action\n\n{state['current']['next_action']}.",
            status,
            count=1,
            flags=re.MULTILINE,
        )
        status_blocker = (
            "Authorization is revoked; active testing is prohibited."
            if state["authorization"]["status"] == "revoked"
            else (
                "Authorization basis is pending; record the user statement or "
                "written source before active testing."
                if state["workflow"] in PROTECTED_WORKFLOWS
                and state["authorization"]["status"] == "pending"
                else "None."
            )
        )
        status = re.sub(
            r"^## Blockers\n\n(?:None\.|Authorization basis is pending; record the user statement or written source before active testing\.|Authorization verification is required before active testing\.|Authorization is revoked; active testing is prohibited\.)$",
            lambda _: f"## Blockers\n\n{status_blocker}",
            status,
            count=1,
            flags=re.MULTILINE,
        )
        atomic_write(status_path, status)

        handoff_path = root / "SESSION-HANDOFF.md"
        handoff = handoff_path.read_text(encoding="utf-8")
        handoff = re.sub(
            r"^- Lifecycle: .+$",
            lambda _: f"- Lifecycle: {state['lifecycle']}",
            handoff,
            count=1,
            flags=re.MULTILINE,
        )
        if "- Authorization:" not in handoff:
            lifecycle_line = f"- Lifecycle: {state['lifecycle']}\n"
            handoff = handoff.replace(
                lifecycle_line,
                lifecycle_line
                + f"- Authorization: {state['authorization']['status']}\n",
                1,
            )
        handoff = re.sub(
            r"^- Authorization: .+$",
            lambda _: f"- Authorization: {state['authorization']['status']}",
            handoff,
            count=1,
            flags=re.MULTILINE,
        )
        handoff = re.sub(
            r"^- Scope revision: [0-9]+$",
            lambda _: f"- Scope revision: {state['scope']['revision']}",
            handoff,
            count=1,
            flags=re.MULTILINE,
        )
        handoff = re.sub(
            r"^## Exact Next Actions\n\n1\. .+$",
            lambda _: f"## Exact Next Actions\n\n1. {state['current']['next_action']}.",
            handoff,
            count=1,
            flags=re.MULTILINE,
        )
        external_dependency = (
            "Renewed written authorization and verification."
            if state["authorization"]["status"] == "revoked"
            else (
                "Recorded authorization basis (user statement or written source)."
                if state["workflow"] in PROTECTED_WORKFLOWS
                and state["authorization"]["status"] == "pending"
                else "None."
            )
        )
        handoff = re.sub(
            r"^## External Dependency\n\n(?:None\.|Recorded authorization basis \(user statement or written source\)\.|Written authorization source and verification\.|Renewed written authorization and verification\.)$",
            lambda _: f"## External Dependency\n\n{external_dependency}",
            handoff,
            count=1,
            flags=re.MULTILINE,
        )
        atomic_write(handoff_path, handoff)

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
            raise ValidationError(
                f"credential file permissions must be 600 or stricter: {credentials}"
            )
        sensitive_target_ref = state["scope"].get("sensitive_target_ref")
        if sensitive_target_ref:
            sensitive_target = root / sensitive_target_ref
            if not sensitive_target.is_file():
                raise ValidationError(
                    f"missing sensitive target file: {sensitive_target_ref}"
                )
            if sensitive_target.stat().st_mode & 0o077:
                raise ValidationError(
                    f"sensitive target file permissions must be 600 or stricter: {sensitive_target}"
                )
        return state

    def authorize(
        self,
        root: Path,
        *,
        status: str,
        source: str | None,
    ) -> dict[str, Any]:
        state = self.validate(root)
        if state["workflow"] not in PROTECTED_WORKFLOWS:
            raise ValidationError(
                f"workflow {state['workflow']} does not require authorization changes"
            )
        if status not in {"pending", "user-asserted", "verified", "revoked"}:
            raise ValidationError(f"unsupported authorization status: {status}")
        source = _validated_text(source, "authorization source") if source else None
        if status in {"user-asserted", "verified", "revoked"} and not source:
            raise ValidationError(
                f"authorization source is required for status {status}"
            )

        timestamp = now()
        state["authorization"] = {"status": status, "source": source}
        state["scope"]["revision"] += 1
        state["scope"]["reviewed_at"] = timestamp
        state["timestamps"]["updated_at"] = timestamp
        if status in AUTHORIZED_STATUSES and state["current"]["next_action"].startswith(
            "Record and verify"
        ):
            state["current"]["next_action"] = self._first_action(state["workflow"])
        elif status == "revoked":
            state["lifecycle"] = "blocked"
            state["current"]["stop_reason"] = "Authorization revoked"
            state["current"]["next_action"] = (
                "Stop active testing and preserve evidence"
            )
        dump_yaml(root / "engagement.yaml", state)

        scope_path = root / "notes" / "SCOPE.md"
        scope = scope_path.read_text(encoding="utf-8")
        scope = re.sub(
            r"^Reviewed: .+$",
            f"Reviewed: {timestamp}",
            scope,
            count=1,
            flags=re.MULTILINE,
        )
        scope = re.sub(
            r"^Revision: [0-9]+$",
            f"Revision: {state['scope']['revision']}",
            scope,
            count=1,
            flags=re.MULTILINE,
        )
        scope = re.sub(
            r"^- Status: .+$", f"- Status: {status}", scope, count=1, flags=re.MULTILINE
        )
        scope = re.sub(
            r"^- Source: .+$",
            f"- Source: {_markdown_text(source or 'Not supplied')}",
            scope,
            count=1,
            flags=re.MULTILINE,
        )
        atomic_write(scope_path, scope)
        self._sync_control_snapshots(root, state)
        return self.validate(root)

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
                result.append(
                    {"slug": path.name, "error": str(error), "path": str(path)}
                )
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

    def transition(
        self, root: Path, lifecycle: str, reason: str | None = None
    ) -> dict[str, Any]:
        state = self.validate(root)
        current = state["lifecycle"]
        if lifecycle == current:
            return state
        if lifecycle not in TRANSITIONS.get(current, set()):
            raise ValidationError(
                f"invalid lifecycle transition: {current} -> {lifecycle}"
            )
        timestamp = now()
        state["lifecycle"] = lifecycle
        state["timestamps"]["updated_at"] = timestamp
        state["checkpoint"]["updated_at"] = timestamp
        state["current"]["stop_reason"] = (
            reason if lifecycle in {"paused", "blocked", "closed"} else None
        )
        dump_yaml(root / "engagement.yaml", state)
        self._sync_control_snapshots(root, state)
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
