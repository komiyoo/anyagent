"""Generate an agent, skill, tool, plugin, or MCP entry inside a workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anyagent.protocol.mcp import MCPServerConfig
from anyagent.scaffold.files import (
    AGENT_SCHEMA_LINE,
    ANYAGENT_SCHEMA_LINE,
    MCP_SCHEMA_REF,
    PLUGIN_ROOT,
    ChangeLog,
    agent_document,
    dump_yaml_with_header,
    ensure_list_item,
    next_steps,
    parse_command_args,
    parse_exposed,
    reject_plaintext_secrets,
    reject_unknown_extra,
    render_template,
    resolve_tool_identity,
    update_json,
    update_yaml,
    validate_agent_id,
    validate_component_name,
)
from anyagent.scaffold.models import AddOptions, ScaffoldError, ScaffoldResult
from anyagent.scaffold.schema_export import write_schema_files


def add_component(opts: AddOptions) -> ScaffoldResult:
    """Generate one component and register it on the target agent or workspace."""

    workspace = Path(opts.workspace).expanduser().resolve()
    if workspace.exists() and not workspace.is_dir():
        raise ScaffoldError(f"workspace is not a directory: {workspace}")
    reject_plaintext_secrets(opts.extra)
    reject_unknown_extra(opts.kind, opts.extra)
    agent_id = validate_agent_id(opts.agent_id)
    _preflight(opts)
    workspace.mkdir(parents=True, exist_ok=True)
    log = ChangeLog(overwrite_as="updated")
    if opts.kind == "agent":
        _add_agent(workspace, opts, log)
    elif opts.kind == "skill":
        _add_skill(workspace, opts, agent_id, log)
    elif opts.kind == "tool":
        _add_tool(workspace, opts, agent_id, log)
    elif opts.kind == "plugin":
        _add_plugin(workspace, opts, log)
    elif opts.kind == "mcp":
        _add_mcp(workspace, opts, agent_id, log)
    else:
        raise ScaffoldError(f"unsupported component kind: {opts.kind}")
    write_schema_files(workspace, log, force=opts.force)
    return ScaffoldResult(
        created=log.created,
        skipped=log.skipped,
        updated=log.updated,
        next_steps=next_steps(workspace),
    )


def _preflight(opts: AddOptions) -> None:
    """Reject bad names and MCP entries before creating any directory."""

    if opts.kind == "tool":
        resolve_tool_identity(opts.name)
        return
    if opts.kind == "mcp":
        MCPServerConfig.model_validate(_mcp_server_entry(opts.extra))
        validate_component_name(opts.name, kind="mcp")
        return
    validate_component_name(opts.name, kind=opts.kind)
    if opts.kind == "agent" and "exposed" in opts.extra:
        parse_exposed(opts.extra["exposed"])


def _add_agent(workspace: Path, opts: AddOptions, log: ChangeLog) -> None:
    name = validate_component_name(opts.name, kind="agent")
    exposed = parse_exposed(opts.extra["exposed"]) if "exposed" in opts.extra else True
    agent_dir = workspace / ".anyagent" / "agents" / name
    log.write(
        agent_dir / "AGENTS.md",
        render_template("agents/added.md.tmpl", name=name),
        force=opts.force,
    )
    document = agent_document(exposed=exposed)
    if agent_dir.joinpath("agent.yaml").is_file():

        def mutate(data: dict[str, Any]) -> None:
            if exposed is False:
                data["exposed"] = False

        update_yaml(agent_dir / "agent.yaml", AGENT_SCHEMA_LINE, mutate, log)
        return
    log.write(
        agent_dir / "agent.yaml",
        dump_yaml_with_header([], document, AGENT_SCHEMA_LINE),
        force=opts.force,
    )


def _add_skill(workspace: Path, opts: AddOptions, agent_id: str, log: ChangeLog) -> None:
    name = validate_component_name(opts.name, kind="skill")
    log.write(
        workspace / ".anyagent" / "skills" / name / "SKILL.md",
        render_template(
            "skills/added.md.tmpl",
            name=name,
            description=f"Use when the {name} skill applies.",
            short_description=name,
        ),
        force=opts.force,
    )
    _ensure_agent_markdown(workspace, agent_id, log, force=opts.force)

    def mutate(data: dict[str, Any]) -> None:
        ensure_list_item(data, ("skills", "default_selected"), name)

    update_yaml(_agent_yaml(workspace, agent_id), AGENT_SCHEMA_LINE, mutate, log)


def _add_tool(workspace: Path, opts: AddOptions, agent_id: str, log: ChangeLog) -> None:
    plugin_id, tool_name, category = resolve_tool_identity(opts.name)
    description = f"Generated tool {tool_name}. Replace the handler body."
    plugin_dir = workspace / PLUGIN_ROOT / plugin_id
    values = {
        "plugin_id": plugin_id,
        "tool_name": tool_name,
        "category": category,
        "description": description,
    }
    log.write(plugin_dir / "plugin.json", render_template("plugins/tool/plugin.json.tmpl", **values), force=opts.force)
    log.write(plugin_dir / "plugin.py", render_template("plugins/tool/plugin.py.tmpl", **values), force=opts.force)
    log.write(plugin_dir / "README.md", render_template("plugins/tool/README.md.tmpl", **values), force=opts.force)
    _ensure_plugin_root(workspace, log)
    _ensure_agent_markdown(workspace, agent_id, log, force=opts.force)

    def mutate(data: dict[str, Any]) -> None:
        ensure_list_item(data, ("tools", "requested_tool_names"), tool_name)

    update_yaml(_agent_yaml(workspace, agent_id), AGENT_SCHEMA_LINE, mutate, log)


def _add_plugin(workspace: Path, opts: AddOptions, log: ChangeLog) -> None:
    name = validate_component_name(opts.name, kind="plugin")
    description = f"Plugin skeleton {name}. Register tools from register() when they are ready."
    plugin_dir = workspace / PLUGIN_ROOT / name
    values = {"plugin_id": name, "description": description}
    log.write(plugin_dir / "plugin.json", render_template("plugins/plugin/plugin.json.tmpl", **values), force=opts.force)
    log.write(plugin_dir / "plugin.py", render_template("plugins/plugin/plugin.py.tmpl", **values), force=opts.force)
    log.write(plugin_dir / "README.md", render_template("plugins/plugin/README.md.tmpl", **values), force=opts.force)
    _ensure_plugin_root(workspace, log)


def _add_mcp(workspace: Path, opts: AddOptions, agent_id: str, log: ChangeLog) -> None:
    name = validate_component_name(opts.name, kind="mcp")
    entry = _mcp_server_entry(opts.extra)
    MCPServerConfig.model_validate(entry)
    _ensure_agent_markdown(workspace, agent_id, log, force=opts.force)
    mcp_path = workspace / ".anyagent" / "agents" / agent_id / "mcp.json"

    def mutate(data: dict[str, Any]) -> None:
        data.setdefault("$schema", MCP_SCHEMA_REF)
        servers = data.get("mcpServers")
        if servers is None:
            servers = {}
            data["mcpServers"] = servers
        if not isinstance(servers, dict):
            raise ScaffoldError("mcpServers must be an object")
        if name in servers and not opts.force:
            return
        servers[name] = entry

    update_json(mcp_path, mutate, log)


def _mcp_server_entry(extra: dict[str, str]) -> dict[str, Any]:
    url = extra.get("url", "").strip()
    command = extra.get("command", "").strip()
    credential_id = extra.get("credential_id", "").strip()
    args = parse_command_args(extra.get("args", ""))
    if url and command:
        raise ScaffoldError("mcp extra cannot set both url and command")
    if not url and not command:
        raise ScaffoldError("mcp extra requires url or command")
    if args and not command:
        raise ScaffoldError("mcp args require command")
    entry: dict[str, Any] = {}
    if url:
        entry["url"] = url
    if command:
        entry["command"] = command
    if args:
        entry["args"] = args
    if credential_id:
        entry["auth"] = {"credential_id": credential_id}
    return entry


def _ensure_plugin_root(workspace: Path, log: ChangeLog) -> None:
    def mutate(data: dict[str, Any]) -> None:
        ensure_list_item(data, ("plugins", "roots"), PLUGIN_ROOT)

    update_yaml(workspace / ".anyagent" / "anyagent.yaml", ANYAGENT_SCHEMA_LINE, mutate, log)


def _ensure_agent_markdown(workspace: Path, agent_id: str, log: ChangeLog, *, force: bool) -> None:
    path = workspace / ".anyagent" / "agents" / agent_id / "AGENTS.md"
    if path.is_file():
        return
    log.write(path, render_template("agents/added.md.tmpl", name=agent_id), force=force)


def _agent_yaml(workspace: Path, agent_id: str) -> Path:
    return workspace / ".anyagent" / "agents" / agent_id / "agent.yaml"
