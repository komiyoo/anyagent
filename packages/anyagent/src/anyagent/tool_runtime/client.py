from __future__ import annotations

from typing import Any

import httpx

from anyagent.protocol.tool_runtime import (
    CancelRequest,
    CancelResponse,
    ExecuteRequest,
    ExecuteResponse,
    ManifestRequest,
    ManifestResponse,
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
        r.raise_for_status()
        data: Any = r.json()
        return ExecuteResponse.model_validate(data)

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

