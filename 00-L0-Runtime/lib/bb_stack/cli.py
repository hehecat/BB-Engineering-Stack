from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .capabilities import CapabilityRegistry
from .configuration import ConfigurationManager
from .engagement import EngagementManager
from .errors import StackError
from .evaluation import EvaluationManager
from .io import load_yaml
from .keysmith import KeysmithAdapter
from .mail_otp import add_mail_subcommands, run_mail_command
from .paths import StackPaths
from .portable import PortableManager
from .profiles import ProfileRegistry
from .runtime import RuntimeManager
from .skills import SkillRegistry
from .status import StackStatus
from .updates import UpdateManager
from .validation import validate
from .workspace import ROUTES, WorkspaceManager


def emit(value: Any, json_output: bool = False) -> None:
    if json_output or isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, ensure_ascii=True, default=str))
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bb-stack",
        description="BB Engineering Stack L0-L5 control plane",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    paths = commands.add_parser("paths", help="show resolved source/runtime/work paths")
    paths.add_argument("--json", action="store_true")

    validate_cmd = commands.add_parser("validate", help="validate all stack contracts")
    validate_cmd.add_argument("--json", action="store_true")

    configure = commands.add_parser(
        "configure", help="set non-secret machine options and regenerate env.sh"
    )
    configure.add_argument("--proxy-mode", choices=["direct", "mihomo"])
    configure.add_argument("--http-proxy")
    configure.add_argument("--socks-proxy")
    configure.add_argument("--h1-username")
    configure.add_argument("--filecodebox-url")
    configure.add_argument("--extra-path")
    configure.add_argument("--show", action="store_true")
    configure.add_argument("--json", action="store_true")

    portable = commands.add_parser(
        "portable", help="export, inspect, or import non-secret machine intent"
    )
    portable_sub = portable.add_subparsers(dest="portable_command", required=True)
    portable_export = portable_sub.add_parser("export")
    portable_export.add_argument("output", type=Path)
    portable_export.add_argument("--force", action="store_true")
    portable_export.add_argument("--json", action="store_true")
    portable_inspect = portable_sub.add_parser("inspect")
    portable_inspect.add_argument("source", type=Path)
    portable_inspect.add_argument("--json", action="store_true")
    portable_import = portable_sub.add_parser("import")
    portable_import.add_argument("source", type=Path)
    portable_import.add_argument("--yes", action="store_true")
    portable_import.add_argument("--force", action="store_true")
    portable_import.add_argument("--json", action="store_true")

    evaluation = commands.add_parser(
        "eval", help="run static contracts or an isolated real-Agent behavior evaluation"
    )
    evaluation_sub = evaluation.add_subparsers(dest="eval_command", required=True)
    evaluation_contracts = evaluation_sub.add_parser("contracts")
    evaluation_contracts.add_argument("--json", action="store_true")
    evaluation_agent = evaluation_sub.add_parser("agent")
    evaluation_agent.add_argument("--profile", default="ctf-quick")
    evaluation_agent.add_argument("--timeout", type=int, default=180)
    evaluation_agent.add_argument("--model", default="sonnet")
    evaluation_agent.add_argument("--max-budget-usd", type=float, default=1.0)
    evaluation_agent.add_argument("--json", action="store_true")

    status = commands.add_parser(
        "status", help="show unified paths, Prompt, Skills, MCP, runtime, and personal configuration"
    )
    status.add_argument(
        "--profile",
        default="ctf-web",
        choices=["minimal", "ctf-web", "web", "android", "reverse"],
    )
    status.add_argument("--workflow-profile")
    status.add_argument(
        "--platform",
        choices=["generic-vdp", "hackerone", "butian", "standalone-ctf", "local-lab"],
    )
    status.add_argument("--probe-mcp", action="store_true")
    status.add_argument("--include-high-context-mcp", action="store_true")
    status.add_argument("--check-external", action="store_true")
    status.add_argument("--engagement")
    status.add_argument("--require-agent-eval", action="store_true")
    status.add_argument("--strict", action="store_true")
    status.add_argument("--json", action="store_true")

    mail = commands.add_parser(
        "mail", help="configure and query the optional lab OTP mailbox"
    )
    add_mail_subcommands(mail)

    bootstrap = commands.add_parser("bootstrap", help="create the local runtime and install a profile")
    bootstrap.add_argument("--profile", default="ctf-web", choices=["minimal", "ctf-web", "web", "android", "reverse"])
    bootstrap.add_argument(
        "--work-root",
        type=Path,
        help="workspace root (recommended default: $HOME/BB-Workspaces)",
    )
    bootstrap.add_argument("--with-optional", action="store_true")
    bootstrap.add_argument("--skip-tools", action="store_true")
    bootstrap.add_argument("--skip-node", action="store_true")
    bootstrap.add_argument("--skip-skills", action="store_true")
    bootstrap.add_argument("--dry-run", action="store_true")
    bootstrap.add_argument("--json", action="store_true")

    workspace = commands.add_parser(
        "workspace", help="initialize, inspect, or route the natural-language Claude workspace"
    )
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_init = workspace_sub.add_parser("init")
    workspace_init.add_argument("--work-root", type=Path)
    workspace_init.add_argument("--force", action="store_true")
    workspace_init.add_argument("--dry-run", action="store_true")
    workspace_init.add_argument("--json", action="store_true")
    workspace_status = workspace_sub.add_parser("status")
    workspace_status.add_argument("--json", action="store_true")
    workspace_route = workspace_sub.add_parser("route")
    workspace_route.add_argument("--kind", choices=sorted(ROUTES))
    workspace_route.add_argument("--target")
    workspace_route.add_argument("--slug")
    workspace_route.add_argument(
        "--platform",
        choices=["generic-vdp", "hackerone", "butian", "standalone-ctf", "local-lab"],
    )
    workspace_route.add_argument(
        "--mode", choices=["interactive", "continuous"]
    )
    workspace_route.add_argument("--json", action="store_true")

    profile = commands.add_parser("profile", help="list, validate, or render runtime profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true")
    profile_validate = profile_sub.add_parser("validate")
    profile_validate.add_argument("name", nargs="?")
    profile_validate.add_argument("--json", action="store_true")
    profile_render = profile_sub.add_parser("render")
    profile_render.add_argument("name")
    profile_render.add_argument("--platform")
    profile_render.add_argument("--engagement")
    profile_render.add_argument("--output-dir", type=Path)
    profile_render.add_argument("--json", action="store_true")

    new = commands.add_parser("new", help="create a new isolated work unit")
    new.add_argument("slug")
    new.add_argument("target")
    new.add_argument("--workflow", choices=["bug-bounty", "ctf", "lab"], default="ctf")
    new.add_argument("--platform")
    new.add_argument("--mode", choices=["interactive", "continuous"], default="interactive")
    new.add_argument("--title")
    new.add_argument("--authorization-source")
    new.add_argument("--json", action="store_true")

    engagement = commands.add_parser("engagement", help="manage L3 engagement state")
    engagement_sub = engagement.add_subparsers(dest="engagement_command", required=True)
    engagement_list = engagement_sub.add_parser("list")
    engagement_list.add_argument("--json", action="store_true")
    engagement_validate = engagement_sub.add_parser("validate")
    engagement_validate.add_argument("engagement", nargs="?")
    engagement_validate.add_argument("--json", action="store_true")
    checkpoint = engagement_sub.add_parser("checkpoint")
    checkpoint.add_argument("engagement", nargs="?")
    checkpoint.add_argument("--json", action="store_true")
    for action in ("pause", "block", "close", "resume", "reopen"):
        transition = engagement_sub.add_parser(action)
        transition.add_argument("engagement", nargs="?")
        transition.add_argument("--reason")
        transition.add_argument("--json", action="store_true")
    migrate = engagement_sub.add_parser("migrate")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("slug")
    migrate.add_argument("target")
    migrate.add_argument("--workflow", choices=["bug-bounty", "ctf", "lab"], default="bug-bounty")
    migrate.add_argument("--platform")
    migrate.add_argument("--yes", action="store_true")
    migrate.add_argument("--json", action="store_true")

    skills = commands.add_parser("skills", help="validate and install versioned Skills")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_list = skills_sub.add_parser("list")
    skills_list.add_argument("--json", action="store_true")
    skills_validate = skills_sub.add_parser("validate")
    skills_validate.add_argument("--json", action="store_true")
    skills_install = skills_sub.add_parser("install")
    skills_install.add_argument("--profile", required=True, choices=["minimal", "ctf-web", "web", "android", "reverse"])
    skills_install.add_argument("--agent", choices=["claude", "codex", "both"], default="claude")
    skills_install.add_argument("--required-only", action="store_true")
    skills_install.add_argument("--force", action="store_true")
    skills_install.add_argument("--json", action="store_true")
    skills_status = skills_sub.add_parser("status")
    skills_status.add_argument("--profile", required=True, choices=["minimal", "ctf-web", "web", "android", "reverse"])
    skills_status.add_argument("--agent", choices=["claude", "codex"], default="claude")
    skills_status.add_argument("--json", action="store_true")

    mcp = commands.add_parser("mcp", help="render or probe MCP configuration")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_render = mcp_sub.add_parser("render")
    mcp_render.add_argument("--profile", required=True, choices=["minimal", "ctf-web", "web", "android", "reverse"])
    mcp_render.add_argument("--output", type=Path, required=True)
    mcp_render.add_argument("--artifact-root", type=Path, required=True)
    mcp_render.add_argument("--include-high-context", action="store_true")
    mcp_render.add_argument("--json", action="store_true")
    mcp_probe = mcp_sub.add_parser("probe")
    mcp_probe.add_argument("config", type=Path)
    mcp_probe.add_argument("--timeout", type=int, default=25)
    mcp_probe.add_argument("--json", action="store_true")

    doctor = commands.add_parser("doctor", help="audit runtime, Skills, capabilities, and MCP readiness")
    doctor.add_argument("--profile", default="ctf-web", choices=["minimal", "ctf-web", "web", "android", "reverse"])
    doctor.add_argument("--engagement")
    doctor.add_argument("--strict", action="store_true")
    doctor.add_argument("--probe-mcp", action="store_true")
    doctor.add_argument("--json", action="store_true")

    keysmith = commands.add_parser("keysmith", help="manage optional persistent Prompt deployment")
    keysmith_sub = keysmith.add_subparsers(dest="keysmith_command", required=True)
    keysmith_fetch = keysmith_sub.add_parser("fetch")
    keysmith_fetch.add_argument("--json", action="store_true")
    keysmith_install = keysmith_sub.add_parser("install")
    keysmith_install.add_argument("--profile", required=True, choices=["ctf-replacement", "lab-replacement"])
    keysmith_install.add_argument("--yes", action="store_true")
    keysmith_install.add_argument("--json", action="store_true")
    keysmith_status = keysmith_sub.add_parser("status")
    keysmith_status.add_argument("--json", action="store_true")
    keysmith_uninstall = keysmith_sub.add_parser("uninstall")
    keysmith_uninstall.add_argument("--yes", action="store_true")
    keysmith_uninstall.add_argument("--json", action="store_true")

    updates = commands.add_parser("updates", help="check, stage, validate, promote, or roll back updates")
    updates_sub = updates.add_subparsers(dest="updates_command", required=True)
    updates_check = updates_sub.add_parser("check")
    update_scope = updates_check.add_mutually_exclusive_group()
    update_scope.add_argument("--all", action="store_true")
    update_scope.add_argument("--skills", action="store_true")
    update_scope.add_argument("--mcp", action="store_true")
    update_scope.add_argument("--tools", action="store_true")
    updates_check.add_argument("--name")
    updates_check.add_argument("--json", action="store_true")
    updates_stage = updates_sub.add_parser("stage")
    updates_stage.add_argument("name")
    updates_stage.add_argument("--json", action="store_true")
    updates_validate = updates_sub.add_parser("validate")
    updates_validate.add_argument("name", nargs="?")
    updates_validate.add_argument("--json", action="store_true")
    updates_promote = updates_sub.add_parser("promote")
    updates_promote.add_argument("name")
    updates_promote.add_argument("--json", action="store_true")
    updates_rollback = updates_sub.add_parser("rollback")
    updates_rollback.add_argument("name")
    updates_rollback.add_argument("--json", action="store_true")

    launch = commands.add_parser("launch", help="render a profile and exec Claude Code in the work unit")
    launch.add_argument("--profile", default="ctf-quick")
    launch.add_argument("--engagement")
    launch.add_argument("--platform")
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("--include-high-context-mcp", action="store_true")
    launch.add_argument("claude_args", nargs=argparse.REMAINDER)
    return parser


def command(args: argparse.Namespace, paths: StackPaths) -> int:
    if args.command == "paths":
        emit(RuntimeManager(paths).runtime_status()["paths"], args.json)
        return 0
    if args.command == "validate":
        stack = load_yaml(paths.root / "stack.yaml")
        validate(stack, paths.root / "schema" / "stack.schema.json", "stack manifest")
        result = {
            "stack": "valid",
            "runtime": RuntimeManager(paths).validate_config(),
            "runtime_profiles": ProfileRegistry(paths).validate_all(),
            "skill_count": len(SkillRegistry(paths).validate_all()),
            "l5_profiles": CapabilityRegistry(paths).validate_all(),
            "updates": UpdateManager(paths).validate_catalog(),
        }
        emit(result, args.json)
        return 0
    if args.command == "configure":
        manager = ConfigurationManager(paths)
        if args.show:
            emit(manager.snapshot(), args.json)
            return 0
        option_map = {
            "BB_PROXY_MODE": args.proxy_mode,
            "BB_HTTP_PROXY": args.http_proxy,
            "BB_SOCKS_PROXY": args.socks_proxy,
            "BB_H1_USERNAME": args.h1_username,
            "BB_FILECODEBOX_URL": args.filecodebox_url,
            "BB_EXTRA_PATH": args.extra_path,
        }
        updates = {key: value for key, value in option_map.items() if value is not None}
        if not updates:
            updates = manager.interactive_updates()
        result = manager.configure(updates)
        result["env_file"] = str(RuntimeManager(paths).write_environment())
        result["workspace"] = WorkspaceManager(paths).initialize()
        result["reload"] = f"source {paths.env_file}"
        emit(result, args.json)
        return 0
    if args.command == "portable":
        manager = PortableManager(paths)
        if args.portable_command == "export":
            emit(manager.export(args.output, force=args.force), args.json)
        elif args.portable_command == "inspect":
            emit(manager.inspect(args.source), args.json)
        else:
            result = manager.import_document(
                args.source, yes=args.yes, force=args.force
            )
            if args.yes:
                result["env_file"] = str(RuntimeManager(paths).write_environment())
                result["workspace"] = WorkspaceManager(paths).initialize()
                result["reload"] = f"source {paths.env_file}"
            emit(result, args.json)
        return 0
    if args.command == "eval":
        manager = EvaluationManager(paths)
        if args.eval_command == "contracts":
            result = manager.contracts()
        else:
            result = manager.agent(
                args.profile,
                timeout=args.timeout,
                model=args.model,
                max_budget_usd=args.max_budget_usd,
            )
        emit(result, args.json)
        return 0 if result["passed"] else 1
    if args.command == "status":
        manager = StackStatus(paths)
        report = manager.collect(
            args.profile,
            workflow_profile=args.workflow_profile,
            platform=args.platform,
            probe_mcp=args.probe_mcp,
            include_high_context_mcp=args.include_high_context_mcp,
            check_external=args.check_external,
            engagement=args.engagement,
            require_agent_eval=args.require_agent_eval,
        )
        if args.json:
            emit(report, True)
        else:
            print(manager.render_text(report))
        return 1 if args.strict and not report["ready"] else 0
    if args.command == "mail":
        return run_mail_command(args, paths.home)
    if args.command == "bootstrap":
        result = RuntimeManager(paths).bootstrap(
            args.profile,
            include_optional=args.with_optional,
            skip_tools=args.skip_tools,
            skip_node=args.skip_node,
            skip_skills=args.skip_skills,
            dry_run=args.dry_run,
        )
        emit(result, args.json)
        return 0
    if args.command == "workspace":
        manager = WorkspaceManager(paths)
        if args.workspace_command == "init":
            result = manager.initialize(force=args.force, dry_run=args.dry_run)
            if not args.dry_run:
                result["env_file"] = str(RuntimeManager(paths).write_environment())
                result["reload"] = f"source {paths.env_file}"
        elif args.workspace_command == "status":
            result = manager.status()
        else:
            result = manager.route(
                kind=args.kind,
                target=args.target,
                slug=args.slug,
                platform=args.platform,
                mode=args.mode,
            )
        emit(result, args.json)
        return 0
    if args.command == "profile":
        registry = ProfileRegistry(paths)
        if args.profile_command == "list":
            emit(registry.names(), args.json)
        elif args.profile_command == "validate":
            result = [args.name] if args.name and registry.load(args.name) else registry.validate_all()
            emit({"valid": result}, args.json)
        else:
            engagement = paths.engagement(args.engagement) if args.engagement else None
            result = registry.render(
                args.name,
                platform=args.platform,
                engagement=engagement,
                output_dir=args.output_dir,
            )
            emit(asdict(result), args.json)
        return 0
    if args.command == "new":
        root = EngagementManager(paths).create(
            args.slug,
            args.target,
            workflow=args.workflow,
            platform=args.platform,
            mode=args.mode,
            title=args.title,
            authorization_source=args.authorization_source,
        )
        emit({"created": str(root)}, args.json)
        return 0
    if args.command == "engagement":
        manager = EngagementManager(paths)
        if args.engagement_command == "list":
            emit(manager.list(), args.json)
            return 0
        if args.engagement_command == "migrate":
            destination = manager.migrate_legacy(
                args.source,
                args.slug,
                args.target,
                workflow=args.workflow,
                platform=args.platform,
                yes=args.yes,
            )
            emit({"destination": str(destination), "migrated": args.yes}, args.json)
            return 0
        root = paths.engagement(args.engagement)
        if args.engagement_command == "validate":
            emit(manager.validate(root), args.json)
        elif args.engagement_command == "checkpoint":
            emit(manager.checkpoint(root), args.json)
        else:
            lifecycle = {
                "pause": "paused",
                "block": "blocked",
                "close": "closed",
                "resume": "active",
                "reopen": "active",
            }[args.engagement_command]
            emit(manager.transition(root, lifecycle, args.reason), args.json)
        return 0
    if args.command == "skills":
        registry = SkillRegistry(paths)
        if args.skills_command == "list":
            emit(
                {
                    "profiles": registry.profile_names(),
                    "skills": sorted(registry.manifest()["skills"]),
                },
                args.json,
            )
        elif args.skills_command == "validate":
            emit(registry.validate_all(), args.json)
        elif args.skills_command == "install":
            emit(
                registry.install(
                    args.profile,
                    agent=args.agent,
                    include_optional=not args.required_only,
                    force=args.force,
                ),
                args.json,
            )
        else:
            emit(registry.status(args.profile, args.agent), args.json)
        return 0
    if args.command == "mcp":
        registry = CapabilityRegistry(paths)
        if args.mcp_command == "render":
            emit(
                registry.render_mcp(
                    args.profile,
                    args.output.expanduser().resolve(),
                    artifact_root=args.artifact_root.expanduser().resolve(),
                    include_high_context=args.include_high_context,
                ),
                args.json,
            )
        else:
            emit(registry.probe_mcp(args.config.expanduser().resolve(), args.timeout), args.json)
        return 0
    if args.command == "doctor":
        runtime = RuntimeManager(paths).runtime_status()
        engagement = paths.engagement(args.engagement) if args.engagement else None
        artifact_root = engagement / "artifacts" if engagement else paths.generated / "doctor-artifacts"
        l5 = CapabilityRegistry(paths)
        report = l5.doctor(args.profile, artifact_root)
        skill_registry = SkillRegistry(paths)
        skill_status = skill_registry.status(args.profile, "claude")
        required_skills = set(skill_registry.profile(args.profile)["required"])
        missing_skills = sorted(
            item["name"]
            for item in skill_status
            if item["name"] in required_skills
            and item["state"] in {"missing", "conflict"}
        )
        result: dict[str, Any] = {
            "schema_version": 1,
            "profile": args.profile,
            "runtime": runtime,
            "capabilities": report,
            "skills": {"ready": not missing_skills, "missing_or_conflicting": missing_skills, "items": skill_status},
        }
        if engagement:
            result["engagement"] = EngagementManager(paths).validate(engagement)
        if args.probe_mcp:
            mcp_path = paths.generated / "doctor" / args.profile / "mcp.json"
            l5.render_mcp(args.profile, mcp_path, artifact_root=artifact_root)
            result["mcp_probe"] = l5.probe_mcp(mcp_path)
        result["ready"] = bool(
            runtime["venv"]
            and runtime["node_modules"]
            and report["ready"]
            and not missing_skills
        )
        emit(result, args.json)
        return 1 if args.strict and not result["ready"] else 0
    if args.command == "keysmith":
        adapter = KeysmithAdapter(paths)
        if args.keysmith_command == "fetch":
            emit(adapter.fetch(), args.json)
        elif args.keysmith_command == "install":
            emit(adapter.install(args.profile, yes=args.yes), args.json)
        elif args.keysmith_command == "status":
            emit(adapter.status(), args.json)
        else:
            emit(adapter.uninstall(yes=args.yes), args.json)
        return 0
    if args.command == "updates":
        manager = UpdateManager(paths)
        if args.updates_command == "check":
            categories = None
            if args.skills:
                categories = {"skills"}
            elif args.mcp:
                categories = {"mcp"}
            elif args.tools:
                categories = {"tools"}
            emit(manager.check(categories, args.name), args.json)
        elif args.updates_command == "stage":
            emit(manager.stage(args.name), args.json)
        elif args.updates_command == "validate":
            emit(manager.validate_candidates(args.name), args.json)
        elif args.updates_command == "promote":
            emit(manager.promote(args.name), args.json)
        else:
            emit(manager.rollback(args.name), args.json)
        return 0
    if args.command == "launch":
        engagement = paths.engagement(args.engagement) if args.engagement else None
        claude_args = args.claude_args
        if claude_args and claude_args[0] == "--":
            claude_args = claude_args[1:]
        result = RuntimeManager(paths).launch(
            args.profile,
            engagement=engagement,
            platform=args.platform,
            claude_args=claude_args,
            dry_run=args.dry_run,
            include_high_context_mcp=args.include_high_context_mcp,
        )
        emit(result, True)
        return 0
    raise StackError(f"unhandled command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    requested_work_root = getattr(args, "work_root", None)
    if requested_work_root is not None:
        import os

        os.environ["BB_WORK_ROOT"] = str(requested_work_root.expanduser().resolve())
    try:
        return command(args, StackPaths.discover())
    except (StackError, OSError, KeyError, ValueError) as error:
        print(f"bb-stack: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
