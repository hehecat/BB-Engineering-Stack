#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.capabilities import CapabilityRegistry
from bb_stack.data import DataManager
from bb_stack.errors import ValidationError
from bb_stack.io import load_yaml
from bb_stack.paths import StackPaths
from bb_stack.profiles import ProfileRegistry
from bb_stack.runtime import RuntimeManager
from bb_stack.skills import SkillRegistry
from bb_stack.updates import UpdateManager
from bb_stack.workspace import ROUTES


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-contracts-")
        home = Path(self.temporary.name)
        self.paths = StackPaths(
            root=ROOT,
            home=home,
            work_root=home / "work",
            config_home=home / "config",
            claude_config_dir=home / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_registries_validate(self) -> None:
        self.assertEqual(len(ProfileRegistry(self.paths).validate_all()), 18)
        self.assertGreaterEqual(len(SkillRegistry(self.paths).validate_all()), 50)
        self.assertEqual(len(CapabilityRegistry(self.paths).validate_all()), 17)
        runtime = RuntimeManager(self.paths).validate_config()
        self.assertIn("ctf-web", runtime["tool_profiles"])
        self.assertEqual(
            set(runtime["tool_profiles"]),
            set(runtime["data"]["profiles"]),
        )
        self.assertEqual(
            set(runtime["data"]["datasets"]),
            {"seclists", "payloads-all-the-things", "trickest-wordlists"},
        )

    def test_bb_recon_declares_owner(self) -> None:
        source = SkillRegistry(self.paths).source("bb-recon")
        frontmatter = SkillRegistry._frontmatter(source / "SKILL.md")
        self.assertEqual(frontmatter.get("owner"), "hehecat")

    def test_skill_wordlist_paths_use_managed_data_root(self) -> None:
        forbidden = (
            "~/wordlists",
            "/usr/share/wordlists",
            "/usr/share/seclists",
            "/SecLists/",
        )
        offenders: list[str] = []
        for path in (ROOT / "04-L4-Skills").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(value in text for value in forbidden):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])
        catalog = DataManager(self.paths).catalog()
        self.assertEqual(catalog["schema_version"], 1)

    def test_all_prompts_fit_budget_and_have_one_output(self) -> None:
        registry = ProfileRegistry(self.paths)
        for name in registry.names():
            result = registry.render(name)
            self.assertLessEqual(result.token_estimate, result.budget)
            expected = (
                "system.md" if result.prompt_mode == "replacement" else "append.md"
            )
            self.assertEqual(Path(result.output_file).name, expected)
            self.assertEqual(
                len(result.source_fragments), len(set(result.source_fragments))
            )
            self.assertIn(
                "01-L1-Global-Prompt/languages/zh-CN.md",
                result.source_fragments,
            )

    def test_workflow_policy_does_not_leak_between_profiles(self) -> None:
        registry = ProfileRegistry(self.paths)
        for name in registry.names():
            rendered = registry.render(name)
            content = Path(rendered.output_file).read_text(encoding="utf-8")
            if rendered.workflow == "assessment":
                self.assertIn("Authorized Security Assessment Workflow", content)
                self.assertNotIn("Default Production Action Budget", content)
                self.assertNotIn("Optimize for a verified flag", content)
            elif rendered.workflow == "analysis":
                self.assertIn("Security Analysis Workflow", content)
                self.assertNotIn("Authorized Security Assessment Workflow", content)
                self.assertNotIn("Default Production Action Budget", content)
            elif rendered.workflow == "ctf":
                self.assertIn("CTF Workflow", content)
                self.assertNotIn("Authorized Security Assessment Workflow", content)

    def test_cross_domain_skills_are_optional_handoffs(self) -> None:
        registry = SkillRegistry(self.paths)
        web = registry.profile("web")
        self.assertIn("browser-js-orchestrator", web["optional"])
        self.assertNotIn("browser-js-orchestrator", web["required"])
        android = registry.profile("assessment-android")
        self.assertIn("api-security", android["optional"])
        self.assertNotIn("api-security", android["required"])

    def test_route_profile_matrix_has_no_drift(self) -> None:
        profiles = ProfileRegistry(self.paths)
        skills = SkillRegistry(self.paths)
        for kind, route in ROUTES.items():
            with self.subTest(kind=kind):
                profile = profiles.load(route["profile"])
                self.assertEqual(profile["workflow"], route["workflow"])
                self.assertEqual(profile["platform"], route["platform"])
                self.assertEqual(profile["skill_profile"], route["skill_profile"])
                self.assertEqual(profile["l5_profile"], route["l5_profile"])
                selected = skills.profile(route["skill_profile"])
                available = set(selected["required"] + selected["optional"])
                self.assertLessEqual(set(route["skill_route"]), available)

    def test_layer_directories_exist(self) -> None:
        for name in (
            "00-L0-Runtime",
            "01-L1-Global-Prompt",
            "02-L2-Workflow-Profiles",
            "03-L3-Engagement-State",
            "04-L4-Skills",
            "05-L5-MCP-CLI",
            "90-Docs",
            "99-Verification",
        ):
            self.assertTrue((ROOT / name).is_dir(), name)

    def test_required_engagement_templates_are_tracked(self) -> None:
        relative = Path(
            "03-L3-Engagement-State/templates/notes/LAB-CREDS.local.md.example"
        )
        self.assertTrue((ROOT / relative).is_file())
        if (ROOT / ".git").exists():
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(relative)],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0, f"required template is not tracked: {relative}"
            )

    def test_release_versions_match(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], version)
        from bb_stack import __version__

        self.assertEqual(__version__, version)

    def test_committed_npm_lock_uses_canonical_registry(self) -> None:
        lock = (ROOT / "00-L0-Runtime/config/node-runtime/package-lock.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://registry.npmjs.org/", lock)
        self.assertNotIn("registry.npmmirror.com", lock)

    def test_python_runtime_lock_requires_hashes(self) -> None:
        requirements = (ROOT / "00-L0-Runtime/config/requirements.lock").read_text(
            encoding="utf-8"
        )
        self.assertIn("--hash=sha256:", requirements)
        self.assertIn("pyjwt==2.13.0", requirements.lower())
        self.assertIn("requests==2.33.0", requirements.lower())
        source = (ROOT / "00-L0-Runtime/config/requirements.in").read_text(
            encoding="utf-8"
        )
        self.assertIn("PyJWT==2.13.0", source)
        runtime = (ROOT / "00-L0-Runtime/lib/bb_stack/runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--require-hashes"', runtime)

    def test_staged_npm_lock_registry_is_canonicalized(self) -> None:
        lock = {
            "packages": {
                "node_modules/example": {
                    "resolved": "https://registry.npmmirror.com/example/-/example-1.0.0.tgz"
                },
                "node_modules/git-example": {
                    "resolved": "https://github.com/example/archive.tgz"
                },
            }
        }
        UpdateManager._canonicalize_npm_lock(lock, "https://registry.npmmirror.com")
        self.assertEqual(
            lock["packages"]["node_modules/example"]["resolved"],
            "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
        )
        self.assertEqual(
            lock["packages"]["node_modules/git-example"]["resolved"],
            "https://github.com/example/archive.tgz",
        )

    def test_update_candidate_environment_does_not_inherit_credentials(self) -> None:
        candidate = Path(self.temporary.name) / "candidate-env"
        with patch.dict(
            os.environ,
            {"GH_TOKEN": "secret", "AWS_SECRET_ACCESS_KEY": "secret"},
            clear=False,
        ):
            env = UpdateManager(self.paths)._candidate_environment(candidate)
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertEqual(env["HOME"], str(candidate / "sandbox-home"))

    def test_authored_core_has_no_old_machine_paths(self) -> None:
        excluded = {
            ".git",
            ".runtime",
            ".spec-workflow",
            ".venv",
            ".ruff_cache",
            "vendor",
            "__pycache__",
        }
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in excluded for part in path.parts):
                continue
            if path.suffix not in {".md", ".yaml", ".json", ".py", ".sh", ".zsh", ""}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            old_home = "/home/" + "hehecat"
            if old_home in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_core_structured_files_and_whitespace(self) -> None:
        excluded = {
            ".git",
            ".runtime",
            ".spec-workflow",
            ".venv",
            ".ruff_cache",
            "vendor",
            "__pycache__",
        }
        trailing = []
        absolute_homes = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in excluded for part in path.parts):
                continue
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix in {".yaml", ".yml"}:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            if path.suffix in {
                ".md",
                ".yaml",
                ".yml",
                ".json",
                ".py",
                ".sh",
                ".zsh",
                "",
            }:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if any(line.endswith((" ", "\t")) for line in text.splitlines()):
                    trailing.append(str(path.relative_to(ROOT)))
                old_root = "/" + "root" + "/"
                old_home = "/home/" + "hehecat"
                if old_root in text or old_home in text:
                    absolute_homes.append(str(path.relative_to(ROOT)))
        self.assertEqual(trailing, [])
        self.assertEqual(absolute_homes, [])

    def test_source_has_no_engagement_data_directory(self) -> None:
        self.assertFalse((ROOT / "engagements").exists())
        self.assertFalse((ROOT / "recon").exists())

    def test_workspace_router_is_small_and_routes_without_profile_questions(
        self,
    ) -> None:
        router = (
            ROOT / "02-L2-Workflow-Profiles" / "workspace" / "CLAUDE.md"
        ).read_text(encoding="utf-8")
        self.assertLessEqual(len(router.split()), 1200)
        self.assertIn("bb-stack workspace route", router)
        self.assertIn("Do not ask the user to choose an internal Profile", router)
        self.assertIn("Operate `bb-stack`, MCP, and CLI tools", router)
        self.assertIn("Ask one compact question only", router)
        self.assertIn("returned repair commands yourself", router)
        self.assertIn("stack operations, not Engagements", router)
        self.assertIn("`user-asserted`", router)
        self.assertIn("bb-stack data ensure", router)
        for kind in (
            "ctf-web",
            "ctf-android",
            "ctf-reverse",
            "web",
            "web-assessment",
            "android-assessment",
            "android-analysis",
            "ios-assessment",
            "reverse-analysis",
            "network-assessment",
            "cloud-assessment",
            "llm-assessment",
            "source-audit",
            "browser-js",
            "lab",
        ):
            self.assertIn(f"`{kind}`", router)

    def test_source_claude_owns_setup_and_workspace_handoff(self) -> None:
        prompt = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(prompt.split()), 600)
        self.assertIn("Bootstrap `minimal` first", prompt)
        self.assertIn("Operate the stack commands yourself", prompt)
        self.assertIn("read its generated", prompt)
        self.assertIn("Do not perform target work in the source tree", prompt)
        self.assertIn("bb-stack data status", prompt)
        self.assertIn("updates approve", prompt)

    def test_yaml_duplicate_keys_are_rejected(self) -> None:
        duplicate = Path(self.temporary.name) / "duplicate.yaml"
        duplicate.write_text("name: first\nname: second\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "duplicate key 'name'"):
            load_yaml(duplicate)

    def test_mcp_server_names_are_unique(self) -> None:
        registry = CapabilityRegistry(self.paths)
        document = registry.registry()
        document["providers"]["playwright-copy"] = dict(
            document["providers"]["playwright-mcp"]
        )
        original = registry.registry
        registry.registry = lambda: document
        try:
            with self.assertRaisesRegex(
                ValidationError, "MCP server name 'playwright'"
            ):
                registry.validate_all()
        finally:
            registry.registry = original

    def test_update_inventory_covers_every_managed_component(self) -> None:
        manager = UpdateManager(self.paths)
        summary = manager.validate_catalog()
        skill_count = len(SkillRegistry(self.paths).manifest()["skills"])
        self.assertEqual(summary["skills"], skill_count)
        mcp_count = sum(
            provider["kind"] == "mcp"
            for provider in CapabilityRegistry(self.paths)
            .registry()["providers"]
            .values()
        )
        self.assertEqual(summary["mcp"], mcp_count)
        self.assertGreaterEqual(summary["tools"], 20)
        subfinder = manager.inventory({"tools"})["tool.subfinder"]
        self.assertEqual(
            subfinder["package"], "github.com/projectdiscovery/subfinder/v2"
        )
        self.assertTrue(subfinder["install_package"].endswith("/cmd/subfinder"))

    def test_update_check_keeps_manual_snapshots_explicit(self) -> None:
        manager = UpdateManager(self.paths)
        current_revision = manager.inventory({"skills"})["skill.ctf-web"][
            "current_revision"
        ]
        manager._git_remote_revision = lambda repository, branch: current_revision
        self.assertEqual(
            manager.check({"skills"}, "skill.ctf-web")["results"][0]["status"],
            "current",
        )
        self.assertEqual(
            manager.check({"skills"}, "skill.account-takeover")["results"][0]["status"],
            "manual",
        )
        self.assertEqual(
            manager.check({"skills"}, "skill.bb-orchestrator")["results"][0]["status"],
            "stack-owned",
        )

    def test_full_security_skill_updates_have_pinned_channels(self) -> None:
        manager = UpdateManager(self.paths)
        revision = "a1a68f7010a9c97b22336dcbcfde539c492a7109"
        manager._git_remote_revision = lambda repository, branch: revision
        for name in (
            "ios-pentest",
            "network-pentest",
            "cloud-security",
            "sast-orchestration",
            "iac-security",
            "container-security",
            "sca-security",
            "threat-modeling",
        ):
            with self.subTest(name=name):
                result = manager.check({"skills"}, f"skill.{name}")["results"][0]
                self.assertEqual(result["status"], "current")

    def test_unrelated_repository_commit_is_not_a_skill_update(self) -> None:
        manager = UpdateManager(self.paths)
        skill = manager.inventory({"skills"})["skill.ctf-web"]
        manager._git_remote_revision = lambda repository, branch: "f" * 40
        manager._github_tree_digest = lambda component, revision: skill[
            "current_digest"
        ]
        result = manager.check({"skills"}, "skill.ctf-web")["results"][0]
        self.assertEqual(result["status"], "current")
        self.assertNotEqual(result["current"], result["latest"])

    def test_staged_skill_validation_is_isolated(self) -> None:
        manager = UpdateManager(self.paths)
        candidate_root = Path(self.temporary.name) / "candidates"
        candidate_root.mkdir()
        manager._candidate_root = lambda: candidate_root
        candidate = candidate_root / "skill__ctf-web"
        payload = candidate / "payload"
        candidate.mkdir()
        source = SkillRegistry(self.paths).source("ctf-web")
        shutil.copytree(source, payload)
        digest = SkillRegistry.tree_digest(payload)
        (candidate / "candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "component": "skill.ctf-web",
                    "category": "skills",
                    "checker": "github-tree",
                    "current": "0" * 40,
                    "latest": "1" * 40,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "state": "staged",
                    "candidate_digest": digest,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = manager.validate_candidates("skill.ctf-web")[0]
        self.assertEqual(result["state"], "validated")
        self.assertEqual(result["validation"]["digest"], digest)
        self.assertEqual(SkillRegistry.tree_digest(source), digest)
        with self.assertRaisesRegex(ValidationError, "explicit review"):
            manager.promote("skill.ctf-web")

        approved = manager.approve(
            "skill.ctf-web",
            reviewer="security-reviewer",
            note="Reviewed the source diff",
        )
        self.assertEqual(approved["approval"]["reviewer"], "security-reviewer")
        skill_file = payload / "SKILL.md"
        skill_file.write_text(
            skill_file.read_text(encoding="utf-8") + "\n# changed after approval\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "changed after approval"):
            manager.promote("skill.ctf-web")


if __name__ == "__main__":
    unittest.main(verbosity=2)
