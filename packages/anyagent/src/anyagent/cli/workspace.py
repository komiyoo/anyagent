"""Workspace commands: init, add, doctor, agent list, and config show/schema.

File generation and template text live in ``anyagent.scaffold``. This module
only parses arguments and prints the result. Scaffold is imported inside the
command functions so the rest of the CLI imports without that package.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import yaml

from anyagent.config.agents import AgentPackError, AgentSpec, load_agent_catalog
from anyagent.config.loader import ConfigLoadError, EffectiveConfig, LeafSource, load_effective_config
from anyagent.config.models import get_provider_spec, resolve_effective_model_selection
from anyagent.plugins.loader import PluginLoadError, discover_plugin_dirs, load_plugin_manifest
from anyagent.protocol.workspace import WorkspaceDoctorFinding, WorkspaceDoctorReport
from anyagent import scaffold
from anyagent.skills import SkillRoot, default_skill_roots, discover_skills, resolve_disabled_skill_stable_ids

_TEMPLATES = ["basic", "coding-agent", "research-agent", "multi-agent-team"]
_PROVIDERS = ["openai", "anthropic", "gemini", "openai_chat"]
_SANDBOX_MODES = ["disabled", "local-unsafe", "opensandbox", "external"]
_ADD_KINDS = ["agent", "skill", "tool", "mcp", "plugin"]
_AGENT_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
_PRIVILEGED_TOOL_NAMES = frozenset({"admin.credential_set"})


def register_workspace(subparsers: Any, bind: Any) -> None:
    """Register workspace, agent, and config commands."""

    init = subparsers.add_parser("init", help="Create a workspace from a template.")
    init.add_argument("--workspace", default=".", help="Workspace root to initialize.")
    init.add_argument("--agent-id", default="main", help="Agent id to create (default: main).")
    init.add_argument("--template", choices=_TEMPLATES, default="basic", help="Workspace template (default: basic).")
    init.add_argument("--provider", choices=_PROVIDERS, default="openai", help="Model provider (default: openai).")
    init.add_argument("--model", default=None, help="Provider model name.")
    init.add_argument("--base-url", default=None, help="Provider base URL.")
    init.add_argument("--tool", action="append", default=None, help="Requested tool name. May be repeated.")
    init.add_argument("--with-exec", action="store_true", help="Enable the exec tool in the generated agent.")
    init.add_argument("--with-web-fetch", action="store_true", help="Enable core.web_fetch in the generated agent.")
    init.add_argument("--sandbox-mode", choices=_SANDBOX_MODES, default=None, help="Sandbox mode to record.")
    init.add_argument("--with-example-skill", action="store_true", help="Add the example skill.")
    init.add_argument("--force", action="store_true", help="Overwrite files created by this command.")
    init.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    bind(init, ("init",), cmd_init)

    add = subparsers.add_parser("add", help="Generate a workspace component skeleton.")
    add_sub = add.add_subparsers(dest="add_kind", required=True)
    for kind in _ADD_KINDS:
        parser = add_sub.add_parser(kind, help=f"Add a {kind}.")
        parser.add_argument("name", help=f"{kind} name.")
        parser.add_argument("--workspace", default=".", help="Workspace root.")
        parser.add_argument("--agent-id", default="main", help="Agent id that should reference the new component.")
        parser.add_argument("--force", action="store_true", help="Overwrite files created by this command.")
        parser.add_argument("--set", action="append", default=None, help="Extra key=value passed to the generator. May be repeated.")
        parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
        bind(parser, ("add", kind), cmd_add)

    doctor = subparsers.add_parser("doctor", help="Validate an anyagent workspace before serving it.")
    doctor.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    bind(doctor, ("doctor",), cmd_doctor)

    agent = subparsers.add_parser("agent", help="Inspect local workspace agent packs.")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_list = agent_sub.add_parser("list", help="List configured agent packs for a workspace.")
    agent_list.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    agent_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    bind(agent_list, ("agent", "list"), cmd_agent_list)

    config = subparsers.add_parser("config", help="Inspect the effective workspace configuration.")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show", help="Print the effective configuration with secrets masked.")
    config_show.add_argument("--workspace", default=".", help="Workspace root.")
    config_show.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    config_show.add_argument("--sources", action="store_true", help="Include the layer and env var for each value.")
    bind(config_show, ("config", "show"), cmd_config_show)
    config_schema = config_sub.add_parser("schema", help="Export JSON Schemas for workspace config files.")
    config_schema.add_argument("--out", default=None, help="Directory to write schema files into. Prints JSON when omitted.")
    bind(config_schema, ("config", "schema"), cmd_config_schema)


def cmd_init(args: argparse.Namespace) -> int:
    """Call ``anyagent.scaffold.init_workspace`` and print the result."""

    workspace = Path(args.workspace).expanduser().resolve()
    agent_id = _validate_agent_id(str(args.agent_id), flag="--agent-id")
    options = scaffold.InitOptions(
        workspace=workspace,
        agent_id=agent_id,
        template=str(args.template or "basic"),
        provider=str(args.provider or "openai"),
        model=_optional_text(args.model),
        base_url=_optional_text(args.base_url),
        tools=_unique_strings(args.tool),
        with_exec=bool(args.with_exec),
        with_web_fetch=bool(args.with_web_fetch),
        sandbox_mode=args.sandbox_mode,
        with_example_skill=bool(args.with_example_skill),
        force=bool(args.force),
    )
    result = scaffold.init_workspace(options)
    if bool(args.json):
        print(result.model_dump_json(exclude_none=True))
    else:
        print(f"initialized workspace: {_workspace_arg(Path(result.workspace))}")
        print(f"agent: {result.agent_id}")
        for path in result.created:
            print(f"created: {_relative_to_workspace(path, workspace)}")
        for path in result.skipped:
            print(f"skipped: {_relative_to_workspace(path, workspace)}")
        if result.next:
            print(f"next: {_relativize_text(result.next, workspace)}")
    return 0 if result.ok else 1


def cmd_add(args: argparse.Namespace) -> int:
    """Call ``anyagent.scaffold.add_component`` and print the result."""

    kind = str(tuple(args.command_path)[-1])
    name = str(args.name).strip()
    if not name:
        raise SystemExit("component name must be non-empty")
    options = scaffold.AddOptions(
        workspace=Path(args.workspace).expanduser().resolve(),
        kind=kind,
        name=name,
        agent_id=_validate_agent_id(str(args.agent_id), flag="--agent-id"),
        force=bool(args.force),
        extra=_parse_sets(args.set),
    )
    result = scaffold.add_component(options)
    workspace = Path(options.workspace)
    if bool(args.json):
        print(result.model_dump_json())
    else:
        print(f"added {kind} {name}")
        for label in ("created", "skipped", "updated"):
            for path in getattr(result, label):
                print(f"{label}: {_relative_to_workspace(path, workspace)}")
        for step in result.next_steps:
            print(f"next: {_relativize_text(step, workspace)}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    """Print ``EffectiveConfig.redacted_dump()`` and optional leaf sources."""

    workspace = Path(args.workspace).expanduser().resolve()
    try:
        effective = load_effective_config(workspace)
    except ConfigLoadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    redacted = effective.redacted_dump()
    runtime_env = _runtime_env_report(effective)
    _annotate_runtime_env(redacted, runtime_env)
    sources = effective.sources_dump() if bool(args.sources) else None
    if bool(args.json):
        payload: Any = redacted if sources is None else {"config": redacted, "sources": sources, "runtime_env": runtime_env}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"workspace: {workspace}")
    print(yaml.safe_dump(redacted, sort_keys=False, allow_unicode=True).rstrip())
    _print_runtime_env(runtime_env)
    if sources is not None:
        print("sources:")
        for path, source in sources.items():
            env = f" env={source['env']}" if source.get("env") else ""
            print(f"  {path}: {source['layer']}{env}")
    print(f"next: anyagent doctor --workspace {workspace}")
    return 0


def cmd_config_schema(args: argparse.Namespace) -> int:
    """Print or write the schemas from ``anyagent.scaffold.export_config_schemas``."""

    schemas = scaffold.export_config_schemas()
    if not isinstance(schemas, dict):
        raise SystemExit("export_config_schemas() must return an object")
    if not args.out:
        print(json.dumps(schemas, ensure_ascii=False, indent=2))
        return 0
    directory = Path(args.out).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas.items():
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Validate the workspace and print a human report or ``WorkspaceDoctorReport`` JSON."""

    workspace = Path(args.workspace).expanduser().resolve()
    findings = doctor_workspace(workspace)
    ok = not any(item.level == "error" for item in findings)
    payload = WorkspaceDoctorReport(ok=ok, workspace=str(workspace), findings=findings)
    if bool(args.json):
        print(payload.model_dump_json(exclude_none=True))
    else:
        shown = _workspace_arg(workspace)
        print(f"anyagent doctor: {'ok' if ok else 'failed'}")
        print(f"workspace: {shown}")
        for item in payload.findings:
            print(f"[{item.level}] {item.code}: {_relativize_text(item.message, workspace)}")
        if ok:
            print(f"next: anyagent serve --workspace {shown}")
        else:
            print(f"next: fix the findings above, then re-run anyagent doctor --workspace {shown}")
    return 0 if ok else 1


def _relative_to_workspace(path: str | Path, workspace: Path) -> str:
    """Return a workspace-relative path. Relative inputs stay as written."""

    text = str(path)
    candidate = Path(text)
    if not candidate.is_absolute():
        return text
    root = workspace.resolve()
    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError:
        return text
    if str(relative) in {"", "."}:
        return "."
    return relative.as_posix()


def _relativize_text(text: str, workspace: Path) -> str:
    """Replace an absolute workspace prefix inside free-form command text."""

    root = str(workspace.resolve())
    if root not in text:
        return text
    replaced = text.replace(root + "/", "")
    if root in replaced:
        replaced = replaced.replace(root, _workspace_arg(workspace))
    return replaced


def _workspace_arg(workspace: Path) -> str:
    """Workspace path as the user can pass it from the current directory.

    File paths in the output are workspace-relative, but a command such as
    ``anyagent doctor --workspace <path>`` runs from the caller's directory.
    """

    root = workspace.resolve()
    try:
        relative = root.relative_to(Path.cwd().resolve())
    except ValueError:
        return str(root)
    return relative.as_posix() or "."


def _runtime_env_report(effective: EffectiveConfig) -> list[dict[str, Any]]:
    """Name and credential id only. Hydration state comes from the last apply, never values."""

    from anyagent.server.runtime.workspace_env import last_runtime_env_hydration, runtime_env_bindings

    hydrated = {
        (item.name, item.credential_id): item.applied
        for item in last_runtime_env_hydration()
    }
    rows: list[dict[str, Any]] = []
    for binding in runtime_env_bindings(effective):
        rows.append(
            {
                "name": binding.name,
                "credential_id": binding.credential_id,
                "hydrated": bool(hydrated.get((binding.name, binding.credential_id), False)),
            }
        )
    return rows


def _annotate_runtime_env(redacted: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    credentials = redacted.get("credentials")
    if not isinstance(credentials, dict):
        return
    entries = credentials.get("runtime_env")
    if not isinstance(entries, list):
        return
    by_key = {(row["name"], row["credential_id"]): row["hydrated"] for row in rows}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = (entry.get("name"), entry.get("credential_id"))
        entry["hydrated"] = bool(by_key.get(key, False))


def _print_runtime_env(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("runtime_env: none")
        return
    print("runtime_env:")
    for row in rows:
        state = "hydrated" if row["hydrated"] else "not hydrated"
        print(f"  {row['name']} <- {row['credential_id']} ({state})")


def cmd_agent_list(args: argparse.Namespace) -> int:
    """List agent packs in the workspace."""

    workspace = Path(args.workspace).expanduser().resolve()
    catalog = load_agent_catalog(workspace_dir=workspace)
    agents = agent_catalog_rows(catalog)
    payload = {
        "workspace": str(workspace),
        "agents_root": str(catalog.root_dir),
        "agents": agents,
    }
    if bool(args.json):
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    print(f"workspace: {workspace}")
    print(f"agents_root: {catalog.root_dir}")
    for agent in agents:
        tools = ", ".join(agent["requested_tool_names"]) or "-"
        spawn = ", ".join(agent["spawn_allow_agent_ids"]) or "-"
        model = agent["model_default"] or "-"
        print(
            f"- {agent['agent_id']} "
            f"exposed={agent['exposed']} "
            f"sandbox={agent['sandbox_mode']} "
            f"model={model} "
            f"tools={tools} "
            f"spawn={spawn}"
        )
    return 0


def agent_catalog_rows(catalog: Any) -> list[dict[str, Any]]:
    """Return stable agent rows for `agent list` and the serve banner."""

    rows: list[dict[str, Any]] = []
    for pack in sorted(catalog.packs.values(), key=lambda item: item.agent_id):
        rows.append(
            {
                "agent_id": pack.agent_id,
                "exposed": bool(pack.spec.exposed),
                "sandbox_mode": pack.spec.sandbox.mode,
                "model_default": pack.spec.model.default,
                "requested_tool_names": list(pack.spec.tools.requested_tool_names),
                "default_selected_skills": list(pack.spec.skills.default_selected or []),
                "spawn_allow_agent_ids": list(pack.spec.multiagent.spawn_allow_agent_ids or []),
                "path": str(pack.root_dir),
            }
        )
    return rows


def doctor_workspace(workspace: Path) -> list[WorkspaceDoctorFinding]:
    """Collect doctor findings for one workspace."""

    findings: list[WorkspaceDoctorFinding] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append(WorkspaceDoctorFinding.model_validate({"level": level, "code": code, "message": message}))

    effective: EffectiveConfig | None = None
    try:
        effective = load_effective_config(workspace)
    except ConfigLoadError as exc:
        add("error", "config_load_error", str(exc))

    try:
        catalog = load_agent_catalog(workspace_dir=workspace)
    except AgentPackError as exc:
        if effective is not None:
            _report_model(effective, pack=_empty_pack(), add=add)
        add("error", "agent_catalog_invalid", str(exc))
        return findings
    except Exception as exc:  # noqa: BLE001
        add("error", "agent_catalog_error", str(exc))
        return findings

    if any(pack.builtin for pack in catalog.packs.values()):
        add("info", "builtin_main_agent", "no agent pack directory found; using the built-in main agent")
    if not catalog.packs:
        add("error", "no_agents", f"no agent packs found under: {workspace / '.anyagent' / 'agents'}")
        return findings

    if effective is not None:
        _report_models(effective, catalog, add)
        plugin_tools, plugin_errors = _declared_plugin_tools(workspace, effective)
        for path, reason in plugin_errors:
            add("warning", "plugin_manifest_invalid", f"{path}: {reason}")
    else:
        plugin_tools = set()

    known_builtins = set(_builtin_tool_names())
    main = catalog.get("main")
    if main is None:
        add("warning", "missing_main_agent", "no agent_id=main pack found; create one for the default `anyagent serve` entrypoint")
    elif not main.spec.exposed:
        add("error", "main_not_exposed", "agent_id=main exists but exposed=false; `anyagent serve` requires exposed main")

    for pack in catalog.packs.values():
        add("info", "agent_loaded", f"agent {pack.agent_id}: exposed={pack.spec.exposed} sandbox={pack.spec.sandbox.mode}")
        if not pack.spec.tools.requested_tool_names:
            add("warning", "agent_no_tools", f"agent {pack.agent_id} requests no tools")
        _report_unknown_tools(pack, add=add, builtins=known_builtins, plugin_tools=plugin_tools)
        if pack.spec.sandbox.mode == "opensandbox":
            add("error", "opensandbox_unavailable", f"agent {pack.agent_id} uses opensandbox, which this build does not implement")
        _doctor_cli_profiles(add=add, pack=pack, catalog=catalog)
        _doctor_skills(workspace, pack, add)
        _doctor_mcp(pack, add)

    if not findings:
        add("info", "workspace_ok", "workspace is valid")
    return findings


def _report_models(effective: EffectiveConfig, catalog: Any, add: Callable[..., None]) -> None:
    for pack in catalog.packs.values():
        _report_model(effective, pack=pack, add=add)


def _report_model(effective: EffectiveConfig, *, pack: Any, add: Callable[..., None]) -> None:
    selection = resolve_effective_model_selection(pack=pack, models=effective.models)
    provider = selection.provider_name
    base = f"models.providers.{provider}"
    if getattr(pack.spec.model, "default", None):
        model_from = "agent.yaml"
    elif selection.alias:
        model_from = _leaf_origin(effective, f"models.aliases.{selection.alias}.model")
    else:
        model_from = _leaf_origin(effective, "models.default")
    alias_from = _leaf_origin(effective, f"models.aliases.{selection.alias}.provider") if selection.alias else "-"
    add(
        "info",
        "model_provider",
        (
            f"agent {pack.agent_id} model={selection.model or '-'} "
            f"alias={selection.alias or '-'} alias_from={alias_from} "
            f"model_from={model_from} default_from={_leaf_origin(effective, 'models.default')} "
            f"provider={provider} kind={selection.provider_kind} "
            f"provider_from={_leaf_origin(effective, base + '.kind')} "
            f"api_key_from={_leaf_origin(effective, base + '.api_key')} "
            f"base_url_from={_leaf_origin(effective, base + '.base_url')}"
        ),
    )
    if selection.api_key:
        return
    spec = get_provider_spec(selection.provider_kind)
    add(
        "warning",
        "missing_provider_api_key",
        (
            f"agent {pack.agent_id} provider {provider} ({selection.provider_kind}) "
            f"has no api_key; set {spec.default_api_key_env_label} "
            f"or models.providers.{provider}.api_key"
        ),
    )


def _leaf_origin(effective: EffectiveConfig, path: str) -> str:
    source: LeafSource | None = effective.sources.get(path)
    if source is None:
        return "unset"
    if source.env:
        return f"{source.layer} (${{{source.env}}})"
    return source.layer


def _report_unknown_tools(pack: Any, *, add: Callable[..., None], builtins: set[str], plugin_tools: set[str]) -> None:
    cli_names = {profile.name for profile in pack.spec.tools.cli}
    mcp_labels = set(pack.mcp_config.mcpServers) if pack.mcp_config is not None else set()
    for name in pack.spec.tools.requested_tool_names:
        if not isinstance(name, str) or not name.strip() or "*" in name:
            continue
        if name in builtins or name in cli_names or name in plugin_tools:
            continue
        if name.startswith("mcp."):
            parts = name.split(".")
            if len(parts) >= 3 and parts[1] in mcp_labels:
                continue
        add("warning", "unknown_tool", f"agent {pack.agent_id} requests unknown tool: {name}")


def _declared_plugin_tools(workspace: Path, effective: EffectiveConfig) -> tuple[set[str], list[tuple[str, str]]]:
    roots: list[Path] = []
    for raw in [*effective.plugins.roots, *effective.tool_runtime.plugin_roots]:
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = workspace / path
        roots.append(path)
    default_plugins = workspace / "plugins"
    if default_plugins.is_dir():
        roots.append(default_plugins)
    names: set[str] = set()
    errors: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for root in roots:
        for plugin_dir in discover_plugin_dirs(root):
            resolved = plugin_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                manifest = load_plugin_manifest(plugin_dir)
            except PluginLoadError as exc:
                errors.append((str(plugin_dir), str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append((str(plugin_dir), str(exc)))
                continue
            names.update(name for name in manifest.tools if isinstance(name, str))
    return names, errors


@functools.lru_cache(maxsize=1)
def _builtin_tool_names() -> frozenset[str]:
    from anyagent.tool_runtime.builtin_tools import register_builtin_core_tools_sync
    from anyagent.tool_runtime.registry import RESERVED_NAMES, ToolRegistry

    registry = ToolRegistry()
    register_builtin_core_tools_sync(registry)
    names = set(RESERVED_NAMES)
    names.update(tool.name for tool in registry.list_all_tools())
    names.update(_PRIVILEGED_TOOL_NAMES)
    return frozenset(names)


def _doctor_skills(workspace: Path, pack: Any, add: Callable[..., None]) -> None:
    skills, skill_errors = discover_skills(
        [SkillRoot(scope="agent", root=pack.skills_dir), *default_skill_roots(workspace_dir=workspace)]
    )
    for path, reason in skill_errors:
        add("warning", "skill_load_error", f"{path}: {reason}")
    disabled_ids = resolve_disabled_skill_stable_ids(
        pack.spec.skills.disabled_paths,
        skills=skills,
        base_dir=pack.root_dir,
    )
    visible_skill_names = {skill.frontmatter.name for skill in skills if skill.stable_id not in disabled_ids}
    for name in pack.spec.skills.default_selected or []:
        if isinstance(name, str) and name.startswith("skill://"):
            continue
        if name not in visible_skill_names:
            add("warning", "skill_not_found", f"agent {pack.agent_id} selects missing skill: {name}")


def _doctor_mcp(pack: Any, add: Callable[..., None]) -> None:
    if pack.mcp_config is None:
        return
    for label, server in sorted(pack.mcp_config.mcpServers.items()):
        transport = server.infer_transport().value
        add("info", "mcp_server_loaded", f"agent {pack.agent_id} mcp {label}: transport={transport}")
        if server.command:
            command = server.command.strip()
            if os.sep not in command and shutil.which(command) is None:
                add("warning", "mcp_command_missing", f"agent {pack.agent_id} mcp {label} command not found: {command}")
            if server.cwd and not Path(server.cwd).expanduser().exists():
                add("warning", "mcp_cwd_missing", f"agent {pack.agent_id} mcp {label} cwd missing: {server.cwd}")


def _doctor_cli_profiles(*, add: Callable[..., None], pack: Any, catalog: Any) -> None:
    seen_names: set[str] = set()
    for profile in pack.spec.tools.cli:
        if profile.name in seen_names:
            add("error", "cli_profile_duplicate", f"agent {pack.agent_id} defines duplicate cli profile: {profile.name}")
            continue
        seen_names.add(profile.name)
        effective_mode = profile.sandbox or pack.spec.sandbox.mode
        if pack.spec.exposed and effective_mode == "local-unsafe":
            add(
                "warning",
                "cli_profile_local_unsafe_exposed",
                f"agent {pack.agent_id} exposes cli profile {profile.name} via local-unsafe sandbox",
            )
        if profile.env.inherit == "all" and profile.env.ignore_default_excludes:
            add(
                "warning",
                "cli_profile_inherit_all_without_filter",
                f"agent {pack.agent_id} cli profile {profile.name} inherits all env vars without default sensitive filtering",
            )
    if not pack.spec.tools.cli:
        return
    for profile_name, other_agent_id in _find_cli_profile_conflicts(pack=pack, catalog=catalog):
        add(
            "error",
            "cli_profile_conflict",
            f"cli profile {profile_name} conflicts between agent {pack.agent_id} and agent {other_agent_id}",
        )


def _find_cli_profile_conflicts(*, pack: Any, catalog: Any) -> list[tuple[str, str]]:
    conflicts: list[tuple[str, str]] = []
    for sibling in catalog.packs.values():
        if sibling.agent_id == pack.agent_id:
            continue
        sibling_profiles = {profile.name: profile.model_dump() for profile in sibling.spec.tools.cli}
        for profile in pack.spec.tools.cli:
            other = sibling_profiles.get(profile.name)
            if other is None:
                continue
            if other != profile.model_dump():
                conflicts.append((profile.name, sibling.agent_id))
    return conflicts


def _empty_pack() -> Any:
    return SimpleNamespace(agent_id="default", spec=AgentSpec())


def _validate_agent_id(agent_id: str, *, flag: str) -> str:
    value = agent_id.strip()
    if not value:
        raise SystemExit(f"{flag} must be non-empty")
    if len(value) > 64 or any(char not in _AGENT_ID_CHARS for char in value):
        raise SystemExit(f"{flag} must match [a-zA-Z0-9_.-]{{1,64}}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_strings(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for item in values or []:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _parse_sets(values: list[str] | None) -> dict[str, str]:
    extra: dict[str, str] = {}
    for raw in values or []:
        text = str(raw)
        if "=" not in text:
            raise SystemExit("--set expects key=value")
        key, value = text.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit("--set expects key=value")
        extra[key] = value
    return extra
