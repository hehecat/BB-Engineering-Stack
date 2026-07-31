from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .capabilities import CapabilityRegistry
from .errors import CommandError, StackError, ValidationError
from .io import dump_json, dump_yaml, expand, load_json, load_yaml
from .paths import StackPaths
from .profiles import ProfileRegistry
from .runtime import RuntimeManager
from .skills import SkillRegistry
from .validation import validate


class UpdateManager:
    """Audited update discovery with isolated staging and explicit promotion."""

    CATEGORIES = {"skills", "mcp", "tools"}

    def __init__(self, paths: StackPaths):
        self.paths = paths
        self.config_path = paths.root / "00-L0-Runtime" / "config" / "upstreams.yaml"
        self.schema_path = paths.root / "00-L0-Runtime" / "config" / "upstreams.schema.json"
        self.candidate_schema = (
            paths.root / "00-L0-Runtime" / "config" / "update-candidate.schema.json"
        )

    def config(self) -> dict[str, Any]:
        document = load_yaml(self.config_path)
        validate(document, self.schema_path, "upstream registry")
        return document

    def validate_catalog(self) -> dict[str, Any]:
        config = self.config()
        components = config["components"]
        env = self.paths.environment()
        for key in ("candidate_root", "backup_root"):
            managed_path = Path(expand(config["policy"][key], env)).resolve()
            try:
                managed_path.relative_to(self.paths.runtime.resolve())
            except ValueError as error:
                raise ValidationError(
                    f"update policy {key} must stay under {self.paths.runtime}"
                ) from error
        for label, relative in config["inventory"].items():
            inventory_path = (self.paths.root / relative).resolve()
            try:
                inventory_path.relative_to(self.paths.root.resolve())
            except ValueError as error:
                raise ValidationError(f"update inventory {label} escapes stack root") from error
            if not inventory_path.is_file():
                raise ValidationError(f"missing update inventory {label}: {inventory_path}")
        skills = SkillRegistry(self.paths).manifest()["skills"]
        capabilities = CapabilityRegistry(self.paths).registry()["providers"]
        package_json = load_json(
            self.paths.root / config["inventory"]["mcp_packages"]
        )
        dependencies = package_json.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValidationError("MCP package manifest dependencies must be an object")

        seen_targets: set[tuple[str, str]] = set()
        mcp_providers: set[str] = set()
        for name, component in components.items():
            expected_prefix = {
                "skills": "skill.",
                "mcp": "mcp.",
                "tools": "tool.",
            }[component["category"]]
            if not name.startswith(expected_prefix):
                raise ValidationError(
                    f"upstream component/category mismatch: {name} is {component['category']}"
                )
            identity = (component["category"], component["target"])
            if identity in seen_targets:
                raise ValidationError(
                    f"duplicate upstream target: {component['category']} {component['target']}"
                )
            seen_targets.add(identity)
            if component["category"] == "skills":
                if component["target"] not in skills:
                    raise ValidationError(
                        f"upstream {name} references unknown Skill {component['target']}"
                    )
                source = SkillRegistry(self.paths).source(component["target"])
                actual_digest = SkillRegistry.tree_digest(source)
                if actual_digest != component["current_digest"]:
                    raise ValidationError(
                        f"upstream {name} local digest drift: {actual_digest} != "
                        f"{component['current_digest']}"
                    )
            elif component["category"] == "mcp":
                provider_name = component["provider"]
                if provider_name in mcp_providers:
                    raise ValidationError(f"duplicate MCP update provider: {provider_name}")
                mcp_providers.add(provider_name)
                if provider_name not in capabilities or capabilities[provider_name]["kind"] != "mcp":
                    raise ValidationError(
                        f"upstream {name} references unknown MCP provider {provider_name}"
                    )
                if component["target"] not in dependencies:
                    raise ValidationError(
                        f"upstream {name} package is not pinned in node runtime: "
                        f"{component['target']}"
                    )
            elif component["target"] == "keysmith":
                stack = load_yaml(self.paths.root / "stack.yaml")
                if stack["keysmith"]["revision"] != component["current_revision"]:
                    raise ValidationError("Keysmith upstream revision differs from stack.yaml")

        registered_mcp = {
            name for name, provider in capabilities.items() if provider["kind"] == "mcp"
        }
        if mcp_providers != registered_mcp:
            missing = sorted(registered_mcp - mcp_providers)
            extra = sorted(mcp_providers - registered_mcp)
            raise ValidationError(
                "MCP update registry/provider mismatch; "
                f"missing={missing or 'none'}, extra={extra or 'none'}"
            )
        inventory = self.inventory()
        return {
            "components": len(inventory),
            "skills": sum(item["category"] == "skills" for item in inventory.values()),
            "mcp": sum(item["category"] == "mcp" for item in inventory.values()),
            "tools": sum(item["category"] == "tools" for item in inventory.values()),
        }

    def inventory(self, categories: set[str] | None = None) -> dict[str, dict[str, Any]]:
        config = self.config()
        selected = categories or self.CATEGORIES
        unknown = selected - self.CATEGORIES
        if unknown:
            raise ValidationError("unknown update categories: " + ", ".join(sorted(unknown)))

        items: dict[str, dict[str, Any]] = {
            name: dict(component, name=name)
            for name, component in config["components"].items()
            if component["category"] in selected
        }
        explicit_skills = {
            item["target"] for item in items.values() if item["category"] == "skills"
        }
        if "skills" in selected:
            registry = SkillRegistry(self.paths)
            for name, metadata in registry.manifest()["skills"].items():
                component_name = f"skill.{name}"
                if name in explicit_skills:
                    items[component_name]["local_digest"] = registry.tree_digest(
                        registry.source(name)
                    )
                    continue
                provenance = metadata["provenance"]
                items[component_name] = {
                    "name": component_name,
                    "category": "skills",
                    "target": name,
                    "checker": "stack-owned" if provenance == "stack" else "manual",
                    "license": metadata.get("license", "NOASSERTION"),
                    "provenance": provenance,
                    "local_digest": registry.tree_digest(registry.source(name)),
                }
                if metadata.get("repository"):
                    items[component_name]["repository"] = metadata["repository"]
                if metadata.get("revision"):
                    items[component_name]["current"] = metadata["revision"]

        if "mcp" in selected:
            package_json = load_json(
                self.paths.root / config["inventory"]["mcp_packages"]
            )
            dependencies = package_json["dependencies"]
            for item in items.values():
                if item["category"] == "mcp":
                    item["current"] = str(dependencies[item["target"]])

        if "tools" in selected:
            manifest = load_yaml(self.paths.root / config["inventory"]["tools"])
            explicit_targets = {
                item["target"] for item in items.values() if item["category"] == "tools"
            }
            for name, spec in manifest["installers"].items():
                if name in explicit_targets:
                    continue
                items[f"tool.{name}"] = self._tool_inventory(name, spec)
        return dict(sorted(items.items()))

    def _tool_inventory(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        item: dict[str, Any] = {
            "name": f"tool.{name}",
            "category": "tools",
            "target": name,
            "license": "NOASSERTION",
        }
        kind = spec["kind"]
        if kind == "go":
            install_package, version = spec["package"].rsplit("@", 1)
            module = install_package.split("/cmd/", 1)[0]
            item.update(
                checker="go",
                package=module,
                install_package=install_package,
                current=version,
            )
        elif kind == "pipx":
            package, separator, version = spec["package"].partition("==")
            item.update(
                checker="pypi" if separator else "manual",
                package=package,
                current=version or spec["package"],
            )
        elif kind == "git-data" and "github.com/" in spec["repository"]:
            item.update(
                checker="github-commit",
                repository=spec["repository"],
                branch="HEAD",
                current=spec["revision"],
            )
        elif kind in {"archive-binary", "archive-tree", "deb"}:
            urls = [entry["url"] for entry in spec["files"].values()]
            match = re.search(r"github\.com/([^/]+/[^/]+)/releases/download/([^/]+)", urls[0])
            if match:
                item.update(
                    checker="github-release",
                    repository=f"https://github.com/{match.group(1)}",
                    current=match.group(2),
                )
            else:
                item.update(checker="manual", current="pinned-archive")
        elif kind == "apt":
            item.update(checker="apt", packages=list(spec["packages"]), current="system")
        elif kind == "service":
            item.update(checker="manual", current="external-service")
        else:
            item.update(checker="manual", current="unversioned")
        return item

    def check(
        self, categories: set[str] | None = None, name: str | None = None
    ) -> dict[str, Any]:
        self.validate_catalog()
        inventory = self.inventory(categories)
        if name:
            if name not in inventory:
                raise ValidationError(f"unknown update component: {name}")
            inventory = {name: inventory[name]}
        components = list(inventory.values())
        worker_count = min(8, max(1, len(components)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(self._check_safely, components))
        return {
            "schema_version": 1,
            "checked_at": self._now(),
            "results": results,
            "summary": self._summary(results),
        }

    def _check_safely(self, component: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._check_one(component)
        except HTTPError as error:
            failed = self._public_item(component)
            status = "rate-limited" if error.code == 403 else "check-error"
            failed.update(status=status, error=f"HTTP {error.code}: {error.reason}")
            return failed
        except Exception as error:
            failed = self._public_item(component)
            failed.update(status="check-error", error=str(error))
            return failed

    def _check_one(self, component: dict[str, Any]) -> dict[str, Any]:
        result = self._public_item(component)
        checker = component["checker"]
        if checker == "manual":
            result.update(status="manual", current=component.get("current"))
            return result
        if checker == "stack-owned":
            result.update(status="stack-owned", current=component["local_digest"])
            return result
        if checker == "apt":
            result.update(status="system-managed", current="system")
            return result

        current = component.get("current") or component.get("current_revision")
        if checker == "github-tree":
            slug = self._github_slug(component["repository"])
            latest = self._git_remote_revision(component["repository"], component["branch"])
            result["upstream"] = (
                f"https://github.com/{slug}/tree/{component['branch']}/"
                f"{component['subpath']}"
            )
            if latest == component["current_revision"]:
                result["upstream_digest"] = component["current_digest"]
            else:
                result["upstream_digest"] = self._github_tree_digest(component, latest)
        elif checker == "github-commit":
            slug = self._github_slug(component["repository"])
            latest = self._git_remote_revision(component["repository"], component["branch"])
            result["upstream"] = f"https://github.com/{slug}"
        elif checker == "github-release":
            slug = self._github_slug(component["repository"])
            latest = self._git_latest_tag(component["repository"])
            result["upstream"] = f"https://github.com/{slug}"
        elif checker == "npm":
            package = quote(component["target"], safe="")
            latest_data = self._request_json(f"https://registry.npmjs.org/{package}/latest")
            latest = latest_data["version"]
            result["upstream"] = self._repository_url(latest_data.get("repository"))
            result["upstream_license"] = latest_data.get("license")
        elif checker == "pypi":
            latest_data = self._request_json(
                f"https://pypi.org/pypi/{quote(component['package'], safe='')}/json"
            )
            latest = latest_data["info"]["version"]
            result["upstream"] = latest_data["info"].get("project_url")
            result["upstream_license"] = latest_data["info"].get("license") or None
        elif checker == "go":
            module = quote(component["package"], safe="/")
            latest_data = self._request_json(f"https://proxy.golang.org/{module}/@latest")
            latest = latest_data["Version"]
            result["upstream"] = f"https://{component['package']}"
        else:
            raise ValidationError(f"unsupported update checker: {checker}")

        result.update(current=current, latest=latest)
        upstream_license = result.get("upstream_license")
        if (
            upstream_license
            and component["license"] != "NOASSERTION"
            and upstream_license != component["license"]
        ):
            result["status"] = "license-review"
        elif checker == "github-tree" and component["local_digest"] != component["current_digest"]:
            result["status"] = "local-drift"
        elif checker == "github-tree" and result["upstream_digest"] == component["current_digest"]:
            result["status"] = "current"
        else:
            result["status"] = "current" if current == latest else "update-available"
        return result

    def stage(self, name: str) -> dict[str, Any]:
        report = self.check(name=name)
        result = report["results"][0]
        if result["status"] != "update-available":
            raise StackError(f"{name} is not stageable: status={result['status']}")
        component = self.inventory()[name]
        candidate = self._fresh_candidate(name)
        manifest = {
            "schema_version": 1,
            "component": name,
            "category": component["category"],
            "checker": component["checker"],
            "current": result.get("current"),
            "latest": result.get("latest"),
            "created_at": self._now(),
            "state": "staged",
        }
        try:
            if component["checker"] == "github-tree":
                self._stage_github_tree(component, result["latest"], candidate, manifest)
                if manifest["candidate_digest"] == component["current_digest"]:
                    manifest["state"] = "no-content-change"
                    manifest["reason"] = "upstream revision has the same Skill tree digest"
            elif component["checker"] == "npm" and component["category"] == "mcp":
                self._stage_npm(component, result["latest"], candidate, manifest)
            else:
                manifest["state"] = "review-required"
                manifest["reason"] = (
                    "automatic staging is limited to GitHub-tree Skills and npm MCP packages"
                )
        except Exception as error:
            manifest["state"] = "stage-failed"
            manifest["error"] = str(error)
            dump_json(candidate / "candidate.json", manifest)
            raise
        dump_json(candidate / "candidate.json", manifest)
        self._validate_candidate_document(manifest)
        return manifest | {"path": str(candidate)}

    def validate_candidates(self, name: str | None = None) -> list[dict[str, Any]]:
        if name:
            candidates = [self._candidate(name)]
        else:
            root = self._candidate_root()
            candidates = sorted(
                path
                for path in root.glob("*")
                if ".superseded." not in path.name
                and (path / "candidate.json").is_file()
            )
        results = []
        for candidate in candidates:
            results.append(self._validate_candidate(candidate))
        return results

    def _validate_candidate(self, candidate: Path) -> dict[str, Any]:
        manifest_path = candidate / "candidate.json"
        if not manifest_path.is_file():
            raise ValidationError(f"missing candidate manifest: {manifest_path}")
        manifest = self._load_candidate(manifest_path)
        expected_directory = self._directory_name(manifest["component"])
        if candidate.name != expected_directory:
            raise ValidationError(
                f"candidate directory/component mismatch: {candidate.name} != {expected_directory}"
            )
        if manifest["state"] not in {"staged", "validation-failed", "validated"}:
            raise ValidationError(
                f"candidate {manifest['component']} cannot validate from state {manifest['state']}"
            )
        component = self.inventory()[manifest["component"]]
        try:
            if component["checker"] == "github-tree":
                payload = candidate / "payload"
                frontmatter = SkillRegistry._frontmatter(payload / "SKILL.md")
                if frontmatter.get("name") != component["target"]:
                    raise ValidationError("staged Skill frontmatter/name mismatch")
                digest = SkillRegistry.tree_digest(payload)
                if digest != manifest["candidate_digest"]:
                    raise ValidationError("staged Skill digest changed after staging")
                manifest["validation"] = {"skill": "valid", "digest": digest}
            elif component["checker"] == "npm":
                manifest["validation"] = self._validate_npm_mcp(component, candidate)
            else:
                raise ValidationError("candidate requires manual review and cannot be promoted")
            manifest["state"] = "validated"
            manifest["validated_at"] = self._now()
            manifest.pop("error", None)
        except Exception as error:
            manifest["state"] = "validation-failed"
            manifest["error"] = str(error)
            dump_json(manifest_path, manifest)
            raise
        dump_json(manifest_path, manifest)
        return manifest | {"path": str(candidate)}

    def promote(self, name: str) -> dict[str, Any]:
        candidate = self._candidate(name)
        manifest = self._load_candidate(candidate / "candidate.json")
        if manifest["state"] != "validated":
            raise ValidationError(f"candidate {name} must be validated before promotion")
        component = self.inventory()[name]
        fresh = self.check(name=name)["results"][0]
        if (
            fresh["status"] != "update-available"
            or fresh.get("latest") != manifest.get("latest")
        ):
            raise ValidationError(
                f"candidate {name} is stale: upstream status={fresh['status']}, "
                f"latest={fresh.get('latest')}"
            )
        backup = self._new_backup(name)
        if component["checker"] == "github-tree":
            self._promote_skill(component, candidate, backup, manifest)
        elif component["checker"] == "npm":
            self._promote_npm(candidate, backup, manifest)
        else:
            raise ValidationError(f"automatic promotion is unsupported for {name}")
        manifest["state"] = "promoted"
        manifest["promoted_at"] = self._now()
        manifest["backup"] = str(backup)
        dump_json(candidate / "candidate.json", manifest)
        return manifest | {"path": str(candidate)}

    def rollback(self, name: str) -> dict[str, Any]:
        candidate = self._candidate(name)
        manifest = self._load_candidate(candidate / "candidate.json")
        if manifest["state"] != "promoted":
            raise ValidationError(f"candidate {name} is not promoted")
        backup = Path(manifest["backup"]).resolve()
        try:
            backup.relative_to(self._backup_root().resolve())
        except ValueError as error:
            raise ValidationError("candidate backup path escapes managed backup root") from error
        component = self.inventory()[name]
        if component["checker"] == "github-tree":
            source = SkillRegistry(self.paths).source(component["target"])
            replaced = backup / "replaced-at-rollback"
            source.rename(replaced)
            shutil.copytree(backup / "payload", source)
            shutil.copy2(backup / "upstreams.yaml", self.config_path)
        elif component["checker"] == "npm":
            runtime_config = self.paths.root / "00-L0-Runtime" / "config" / "node-runtime"
            for filename in ("package.json", "package-lock.json"):
                shutil.copy2(backup / filename, runtime_config / filename)
            RuntimeManager(self.paths)._node_runtime(False)
        else:
            raise ValidationError(f"automatic rollback is unsupported for {name}")
        self._validate_stack_contracts()
        manifest["state"] = "rolled-back"
        manifest["rolled_back_at"] = self._now()
        dump_json(candidate / "candidate.json", manifest)
        return manifest | {"path": str(candidate)}

    def _stage_github_tree(
        self,
        component: dict[str, Any],
        revision: str,
        candidate: Path,
        manifest: dict[str, Any],
    ) -> None:
        slug = self._github_slug(component["repository"])
        archive = candidate / "upstream.tar.gz"
        self._download(f"https://codeload.github.com/{slug}/tar.gz/{revision}", archive)
        extracted = candidate / "extracted"
        extracted.mkdir()
        with tarfile.open(archive) as handle:
            RuntimeManager._safe_extract(handle, extracted)
        roots = [path for path in extracted.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValidationError("GitHub archive has an unexpected top-level layout")
        source = (roots[0] / component["subpath"]).resolve()
        try:
            source.relative_to(roots[0].resolve())
        except ValueError as error:
            raise ValidationError("GitHub-tree subpath escapes archive") from error
        if not (source / "SKILL.md").is_file():
            raise ValidationError(f"upstream Skill is missing SKILL.md: {component['subpath']}")
        payload = candidate / "payload"
        shutil.copytree(source, payload)
        frontmatter = SkillRegistry._frontmatter(payload / "SKILL.md")
        if frontmatter.get("name") != component["target"]:
            raise ValidationError("upstream Skill frontmatter/name mismatch")
        manifest["candidate_digest"] = SkillRegistry.tree_digest(payload)
        manifest["source"] = f"https://github.com/{slug}/tree/{revision}/{component['subpath']}"

    def _stage_npm(
        self,
        component: dict[str, Any],
        version: str,
        candidate: Path,
        manifest: dict[str, Any],
    ) -> None:
        source = self.paths.root / "00-L0-Runtime" / "config" / "node-runtime"
        for filename in ("package.json", "package-lock.json"):
            shutil.copy2(source / filename, candidate / filename)
        package_json = load_json(candidate / "package.json")
        package_json["dependencies"][component["target"]] = version
        dump_json(candidate / "package.json", package_json)
        npm = shutil.which("npm", path=self.paths.runtime_path())
        if not npm:
            raise CommandError("npm is required to stage an MCP update")
        self._run(
            [
                npm,
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--prefix",
                str(candidate),
            ],
            timeout=120,
        )
        shutil.copy2(
            self.paths.root / "05-L5-MCP-CLI" / "lib" / "mcp_probe.mjs",
            candidate / "mcp_probe.mjs",
        )
        lock = load_json(candidate / "package-lock.json")
        manifest["integrity"] = lock["packages"][f"node_modules/{component['target']}"]["integrity"]

    def _validate_npm_mcp(
        self, component: dict[str, Any], candidate: Path
    ) -> dict[str, Any]:
        npm = shutil.which("npm", path=self.paths.runtime_path())
        node = shutil.which("node", path=self.paths.runtime_path())
        if not npm or not node:
            raise CommandError("node and npm are required to validate an MCP update")
        self._run(
            [
                npm,
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--prefix",
                str(candidate),
            ],
            timeout=180,
        )
        registry = CapabilityRegistry(self.paths)
        provider = registry.registry()["providers"][component["provider"]]
        env = registry._environment(candidate / "artifacts")
        mcp = expand(provider["mcp"], env)
        old_modules = str(self.paths.runtime / "node_modules")
        new_modules = str(candidate / "node_modules")
        launch = {
            "command": mcp["command"],
            "args": [str(value).replace(old_modules, new_modules) for value in mcp["args"]],
        }
        completed = subprocess.run(
            [node, str(candidate / "mcp_probe.mjs"), json.dumps(launch)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CommandError(
                "MCP candidate probe returned invalid JSON: "
                + (completed.stderr.strip() or completed.stdout.strip())
            ) from error
        if not result.get("connected"):
            raise CommandError(f"MCP candidate handshake failed: {result.get('error', result)}")
        return {
            "npm_ci": "passed",
            "mcp_handshake": "passed",
            "tool_count": result.get("tool_count"),
        }

    def _promote_skill(
        self,
        component: dict[str, Any],
        candidate: Path,
        backup: Path,
        manifest: dict[str, Any],
    ) -> None:
        source = SkillRegistry(self.paths).source(component["target"])
        shutil.copy2(self.config_path, backup / "upstreams.yaml")
        source.rename(backup / "payload")
        try:
            shutil.copytree(candidate / "payload", source)
            config = self.config()
            config["components"][manifest["component"]]["current_revision"] = manifest["latest"]
            config["components"][manifest["component"]]["current_digest"] = manifest["candidate_digest"]
            dump_yaml(self.config_path, config)
            self._validate_stack_contracts()
        except Exception:
            if source.exists():
                source.rename(backup / "failed-promotion")
            (backup / "payload").rename(source)
            shutil.copy2(backup / "upstreams.yaml", self.config_path)
            raise

    def _promote_npm(
        self, candidate: Path, backup: Path, manifest: dict[str, Any]
    ) -> None:
        runtime_config = self.paths.root / "00-L0-Runtime" / "config" / "node-runtime"
        for filename in ("package.json", "package-lock.json"):
            shutil.copy2(runtime_config / filename, backup / filename)
            shutil.copy2(candidate / filename, runtime_config / filename)
        try:
            RuntimeManager(self.paths)._node_runtime(False)
            self._validate_stack_contracts()
        except Exception:
            for filename in ("package.json", "package-lock.json"):
                shutil.copy2(backup / filename, runtime_config / filename)
            RuntimeManager(self.paths)._node_runtime(False)
            raise

    def _validate_stack_contracts(self) -> None:
        stack = load_yaml(self.paths.root / "stack.yaml")
        validate(stack, self.paths.root / "schema" / "stack.schema.json", "stack manifest")
        RuntimeManager(self.paths).validate_config()
        ProfileRegistry(self.paths).validate_all()
        SkillRegistry(self.paths).validate_all()
        CapabilityRegistry(self.paths).validate_all()
        self.validate_catalog()

    def _candidate_root(self) -> Path:
        env = self.paths.environment()
        root = Path(expand(self.config()["policy"]["candidate_root"], env))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _backup_root(self) -> Path:
        env = self.paths.environment()
        root = Path(expand(self.config()["policy"]["backup_root"], env))
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _directory_name(name: str) -> str:
        return name.replace(".", "__")

    def _candidate(self, name: str) -> Path:
        if name not in self.inventory():
            raise ValidationError(f"unknown update component: {name}")
        root = self._candidate_root().resolve()
        candidate = (root / self._directory_name(name)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValidationError("candidate path escapes managed candidate root") from error
        if not candidate.is_dir():
            raise ValidationError(f"no staged candidate for {name}")
        return candidate

    def _load_candidate(self, path: Path) -> dict[str, Any]:
        manifest = load_json(path)
        self._validate_candidate_document(manifest)
        return manifest

    def _validate_candidate_document(self, manifest: dict[str, Any]) -> None:
        validate(manifest, self.candidate_schema, "update candidate")

    def _fresh_candidate(self, name: str) -> Path:
        root = self._candidate_root()
        candidate = root / self._directory_name(name)
        if candidate.exists():
            candidate.rename(root / f"{candidate.name}.superseded.{self._timestamp()}")
        candidate.mkdir()
        return candidate

    def _new_backup(self, name: str) -> Path:
        root = self._backup_root() / self._directory_name(name)
        root.mkdir(parents=True, exist_ok=True)
        backup = root / self._timestamp()
        serial = 1
        while backup.exists():
            backup = root / f"{self._timestamp()}.{serial}"
            serial += 1
        backup.mkdir()
        return backup

    def _request_json(self, url: str) -> dict[str, Any]:
        value = self._request_json_value(url)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object from {url}")
        return value

    def _request_json_value(self, url: str) -> Any:
        timeout = int(self.config()["policy"]["network_timeout_seconds"])
        headers = {
            "Accept": "application/vnd.github+json, application/json",
            "User-Agent": "bb-engineering-stack-update-checker/0.2",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token and urlparse(url).netloc.lower() == "api.github.com":
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            url,
            headers=headers,
        )
        with urlopen(request, timeout=timeout) as response:
            value = json.load(response)
        return value

    def _git_remote_revision(self, repository: str, branch: str) -> str:
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        git = shutil.which("git", path=env["PATH"])
        if not git:
            raise CommandError("git is required for GitHub update checks")
        reference = "HEAD" if branch == "HEAD" else f"refs/heads/{branch}"
        try:
            completed = subprocess.run(
                [git, "ls-remote", repository, reference],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(self.config()["policy"]["network_timeout_seconds"]),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CommandError(f"git ls-remote failed for {repository}: {error}") from error
        if completed.returncode != 0 or not completed.stdout.strip():
            detail = completed.stderr.strip() or "empty response"
            raise CommandError(f"git ls-remote failed for {repository}: {detail}")
        revision = completed.stdout.split()[0]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValidationError(f"invalid Git revision returned for {repository}: {revision}")
        return revision

    def _git_latest_tag(self, repository: str) -> str:
        env = self.paths.environment()
        env["PATH"] = self.paths.runtime_path()
        git = shutil.which("git", path=env["PATH"])
        if not git:
            raise CommandError("git is required for GitHub release checks")
        try:
            completed = subprocess.run(
                [git, "ls-remote", "--tags", "--refs", repository],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(self.config()["policy"]["network_timeout_seconds"]),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CommandError(f"git tag check failed for {repository}: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "empty response"
            raise CommandError(f"git tag check failed for {repository}: {detail}")
        tags = []
        for line in completed.stdout.splitlines():
            reference = line.split("\t", 1)[-1]
            tag = reference.removeprefix("refs/tags/")
            match = re.fullmatch(r"v?(\d+(?:\.\d+)+)", tag)
            if match:
                version = tuple(int(part) for part in match.group(1).split("."))
                tags.append((version, tag))
        if not tags:
            raise ValidationError(f"no stable numeric release tags found for {repository}")
        return max(tags)[1]

    def _github_tree_digest(self, component: dict[str, Any], revision: str) -> str:
        cache_root = self.paths.runtime / "update-cache" / "github-tree"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / f"{self._directory_name(component['name'])}.json"
        if cache_path.is_file():
            cached = load_json(cache_path)
            if cached.get("revision") == revision and re.fullmatch(
                r"[0-9a-f]{64}", str(cached.get("digest", ""))
            ):
                return str(cached["digest"])

        slug = self._github_slug(component["repository"])
        with tempfile.TemporaryDirectory(prefix="github-tree-", dir=cache_root) as raw:
            temporary = Path(raw)
            archive = temporary / "upstream.tar.gz"
            self._download(f"https://codeload.github.com/{slug}/tar.gz/{revision}", archive)
            extracted = temporary / "extracted"
            extracted.mkdir()
            with tarfile.open(archive) as handle:
                RuntimeManager._safe_extract(handle, extracted)
            roots = [path for path in extracted.iterdir() if path.is_dir()]
            if len(roots) != 1:
                raise ValidationError("GitHub archive has an unexpected top-level layout")
            source = (roots[0] / component["subpath"]).resolve()
            try:
                source.relative_to(roots[0].resolve())
            except ValueError as error:
                raise ValidationError("GitHub-tree subpath escapes archive") from error
            if not (source / "SKILL.md").is_file():
                raise ValidationError("GitHub-tree update is missing SKILL.md")
            digest = SkillRegistry.tree_digest(source)
        dump_json(
            cache_path,
            {"schema_version": 1, "revision": revision, "digest": digest, "checked_at": self._now()},
        )
        return digest

    def _download(self, url: str, destination: Path) -> None:
        timeout = max(60, int(self.config()["policy"]["network_timeout_seconds"]))
        request = Request(url, headers={"User-Agent": "bb-engineering-stack-update-checker/0.2"})
        temporary = destination.with_suffix(destination.suffix + ".part")
        with urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        os.replace(temporary, destination)

    @staticmethod
    def _github_slug(repository: str) -> str:
        parsed = urlparse(repository.removesuffix(".git"))
        if parsed.netloc.lower() != "github.com":
            raise ValidationError(f"not a GitHub repository: {repository}")
        slug = parsed.path.strip("/")
        if slug.count("/") != 1:
            raise ValidationError(f"invalid GitHub repository: {repository}")
        return slug

    @staticmethod
    def _repository_url(value: Any) -> str | None:
        if isinstance(value, str):
            return value.removeprefix("git+").removesuffix(".git")
        if isinstance(value, dict) and isinstance(value.get("url"), str):
            return value["url"].removeprefix("git+").removesuffix(".git")
        return None

    @staticmethod
    def _public_item(component: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "name",
            "category",
            "target",
            "checker",
            "license",
            "provenance",
            "repository",
            "local_digest",
        )
        return {key: component[key] for key in keys if key in component}

    @staticmethod
    def _summary(results: list[dict[str, Any]]) -> dict[str, int]:
        summary: dict[str, int] = {"total": len(results)}
        for result in results:
            status = str(result["status"])
            summary[status] = summary.get(status, 0) + 1
        return summary

    @staticmethod
    def _run(command: list[str], *, timeout: int) -> None:
        try:
            subprocess.run(command, text=True, timeout=timeout, check=True)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise CommandError(f"command failed: {shlex.join(command)}: {error}") from error

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
