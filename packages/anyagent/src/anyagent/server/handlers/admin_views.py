from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from anyagent.agent_packs import AgentPack
from anyagent.mcp.models import MCPServerConfig
from anyagent.protocol.admin_storage import AdminSandboxWorkspaceRef
from anyagent.protocol.agent_api_internal import AdminMcpServerItem, AdminMcpServersResponse
from anyagent.server.handlers.agent_files import _workspace_agent_file_path


def _read_agent_mcp_json_payload(pack: AgentPack) -> dict[str, Any]:
    path = _workspace_agent_file_path(pack, kind="mcp_json")
    if not path.is_file():
        return {"mcpServers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid mcp.json: {e}") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid mcp.json: file must be a JSON object")
    if "mcpServers" not in payload:
        payload["mcpServers"] = {}
    return payload


def _admin_sandbox_workspace_ref(record: Any) -> AdminSandboxWorkspaceRef:
    return AdminSandboxWorkspaceRef.model_validate(record.model_dump(mode="json", exclude_none=True))


async def _find_sandbox_workspace_ref(state: AnyAgentServerApp, *, workspace_id: str) -> AdminSandboxWorkspaceRef:
    for record in await state.sandbox_manager.list_workspaces():
        ref = _admin_sandbox_workspace_ref(record)
        if ref.workspace_id == workspace_id:
            return ref
    raise HTTPException(status_code=404, detail=f"unknown workspace_id: {workspace_id}")


def _split_session_partition_key(session_partition_key_value: str) -> tuple[str, str]:
    agent_id, separator, session_key = session_partition_key_value.partition("::")
    if not agent_id or separator != "::" or not session_key:
        raise HTTPException(status_code=500, detail="invalid sandbox workspace session_partition_key")
    return agent_id, session_key


def _admin_mcp_servers_response(pack: AgentPack) -> AdminMcpServersResponse:
    local_payload = _read_agent_mcp_json_payload(pack)
    raw_local_servers = local_payload.get("mcpServers")
    local_servers = raw_local_servers if isinstance(raw_local_servers, dict) else {}
    local_labels = {str(label) for label in local_servers.keys()}
    items: list[AdminMcpServerItem] = []
    effective_servers = pack.mcp_config.mcpServers if pack.mcp_config is not None else {}
    for label, cfg in sorted(effective_servers.items()):
        source = "agent" if label in local_labels else "inherited"
        enablement = "disabled" if not cfg.enabled else "enabled"
        if source == "inherited":
            enablement = "inherited"
        items.append(_admin_mcp_server_item(label=label, cfg=cfg, source=source, enablement=enablement))
    return AdminMcpServersResponse(
        agent_id=pack.agent_id,
        configured=bool(items),
        enabled_count=sum(1 for item in items if item.enabled),
        disabled_count=sum(1 for item in items if not item.enabled),
        inherited_count=sum(1 for item in items if item.enablement == "inherited"),
        invalid_count=sum(1 for item in items if item.enablement == "invalid"),
        servers=items,
    )


def _admin_mcp_server_item(*, label: str, cfg: MCPServerConfig, source: str, enablement: str) -> AdminMcpServerItem:
    transport = _mcp_transport_value(cfg)
    tool_filter = None if cfg.tool_filter is None else cfg.tool_filter.model_dump(exclude_none=True)
    return AdminMcpServerItem(
        label=label,
        enabled=bool(cfg.enabled),
        enablement=enablement,  # type: ignore[arg-type]
        transport=transport,
        url=cfg.url,
        command=cfg.command,
        credential_id=None if cfg.auth is None else cfg.auth.credential_id,
        timeout_seconds=cfg.timeout_seconds,
        idle_timeout_seconds=cfg.idle_timeout_seconds,
        tool_filter=tool_filter,
        source=source,  # type: ignore[arg-type]
    )


def _mcp_transport_value(cfg: MCPServerConfig) -> str | None:
    try:
        return cfg.infer_transport().value
    except Exception:
        return None
