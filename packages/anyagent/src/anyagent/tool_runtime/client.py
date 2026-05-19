from __future__ import annotations

from typing import Any

import httpx

from anyagent.protocol.tool_runtime import (
    CancelRequest,
    CancelResponse,
    ExecuteRequest,
    ExecuteResponse,
    ExecuteResponseCancelled,
    ExecuteResponseCompleted,
    ExecuteResponseError,
    ManifestRequest,
    ManifestResponse,
    ToolContext,
)


class ToolRuntimeClient:
    """
    Tool Runtime HTTP Client（v0）。

    约束：
    - 内部鉴权 header 固定使用 Bearer（由部署提供 shared key/mTLS/JWT 均可包一层）。
    - 所有请求/响应以 `anyagent.protocol.tool_runtime` 为单一真源。
    """

    def __init__(
        self,
        *,
        base_url: str,
        internal_key: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._internal_key = internal_key
        self._http = http

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._internal_key}", "content-type": "application/json"}

    async def manifest(self, req: ManifestRequest) -> ManifestResponse:
        url = f"{self._base_url}/internal/tools/manifest"
        if self._http is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True))
        else:
            r = await self._http.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True), timeout=10.0)
        r.raise_for_status()
        data: Any = r.json()
        return ManifestResponse.model_validate(data)

    async def execute(self, req: ExecuteRequest) -> ExecuteResponse:
        url = f"{self._base_url}/internal/tools/execute"
        if self._http is None:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True))
        else:
            r = await self._http.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True), timeout=60.0)
        data: Any = r.json()
        if r.status_code == 409:
            return _parse_execute_response(data)
        r.raise_for_status()
        return _parse_execute_response(data)

    async def cancel(self, req: CancelRequest) -> CancelResponse:
        url = f"{self._base_url}/internal/tools/cancel"
        if self._http is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True))
        else:
            r = await self._http.post(url, headers=self._headers(), json=req.model_dump(exclude_none=True), timeout=10.0)
        r.raise_for_status()
        data: Any = r.json()
        return CancelResponse.model_validate(data)


class ToolsetVersionMismatch(Exception):
    pass


def create_tool_runtime_client(
    *,
    base_url: str,
    internal_key: str,
    http: httpx.AsyncClient | None = None,
) -> ToolRuntimeClient:
    return ToolRuntimeClient(base_url=base_url, internal_key=internal_key, http=http)


async def fetch_manifest_tools(
    *,
    tool_runtime: ToolRuntimeClient,
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
    resp = await tool_runtime.manifest(req)
    tools = [tool.model_dump(exclude_none=True, by_alias=True) for tool in resp.tools]
    return tools, resp.toolset_version


async def execute_tool_runtime_tool(
    *,
    tool_runtime: ToolRuntimeClient,
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
    resp = await tool_runtime.execute(req)
    error = resp.error
    if error is not None and getattr(error, "code", None) == "toolset_version_mismatch":
        raise ToolsetVersionMismatch(str(getattr(error, "message", None) or "toolset_version_mismatch"))
    return resp.model_dump(exclude_none=True)


def _parse_execute_response(data: Any) -> ExecuteResponse:
    if not isinstance(data, dict):
        raise ValueError("tool runtime execute response must be an object")
    status = data.get("status")
    if status == "completed":
        return ExecuteResponseCompleted.model_validate(data)
    if status == "cancelled":
        return ExecuteResponseCancelled.model_validate(data)
    if status == "error":
        return ExecuteResponseError.model_validate(data)
    raise ValueError(f"unknown tool runtime execute response status: {status!r}")
