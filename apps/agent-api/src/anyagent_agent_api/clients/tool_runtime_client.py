from __future__ import annotations

from typing import Any

import httpx

from anyagent.protocol.tool_runtime import ExecuteRequest, ExecuteResponse, ManifestRequest, ToolContext
from anyagent.tool_runtime.client import ToolRuntimeClient

from ..settings import Settings


class ToolsetVersionMismatch(Exception):
    pass


def _create_tool_runtime_client(*, client: httpx.AsyncClient, settings: Settings) -> ToolRuntimeClient:
    """Create Tool Runtime client bound to the app-level shared AsyncClient."""

    return ToolRuntimeClient(
        base_url=str(settings.tool_runtime_base_url),
        internal_key=settings.tool_runtime_internal_key,
        http=client,
    )


async def fetch_manifest(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    agent_id: str,
    session_key: str | None,
    enabled_skills: list[str] | None,
    requested_tool_names: list[str] | None,
    requested_tools: list[dict[str, Any]] | None,
    context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], int]:
    req = ManifestRequest(
        agent_id=agent_id,
        session_key=session_key,
        context=ToolContext.model_validate(context or {}),
        enabled_skills=enabled_skills,
        requested_tool_names=requested_tool_names,
        requested_tools=requested_tools,
    )
    tr_client = _create_tool_runtime_client(client=client, settings=settings)
    resp = await tr_client.manifest(req)
    tools = [t.model_dump(exclude_none=True, by_alias=True) for t in resp.tools]
    return tools, resp.toolset_version


async def execute_tool(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    agent_id: str,
    session_key: str | None,
    response_id: str,
    tool_call_id: str,
    tool_name: str,
    arguments_json: Any,
    context: dict[str, Any] | None,
    deadline_ms: int | None,
    toolset_version: int | None,
) -> dict[str, Any]:
    req = ExecuteRequest(
        agent_id=agent_id,
        session_key=session_key or "ephemeral",
        response_id=response_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments_json=arguments_json,
        context=ToolContext.model_validate(context or {}),
        deadline_ms=deadline_ms,
        toolset_version=toolset_version,
    )

    url = str(settings.tool_runtime_base_url).rstrip("/") + "/internal/tools/execute"
    headers = {"authorization": f"Bearer {settings.tool_runtime_internal_key}", "content-type": "application/json"}
    r = await client.post(url, headers=headers, json=req.model_dump(exclude_none=True), timeout=60.0)

    if r.status_code == 409:
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            data = None
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("code") == "toolset_version_mismatch":
            raise ToolsetVersionMismatch(str(err.get("message") or "toolset_version_mismatch"))

    r.raise_for_status()
    data = r.json()
    resp = ExecuteResponse.model_validate(data)
    return resp.model_dump(exclude_none=True)
