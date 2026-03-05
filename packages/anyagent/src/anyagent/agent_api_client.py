from __future__ import annotations

"""
anyagent Client SDK — 资源型命名空间入口。

提供 ``AnyAgent`` 入口类，通过子命名空间组织能力：

- ``client.responses`` — OpenAI Responses API 兼容面（委托 OpenAI 官方 SDK）
- ``client.events``    — 内部观测 / replay（/internal/events/*）
- ``client.skills``    — 技能发现（/internal/skills/list）

设计决策：docs/architecture/decisions/openai-first-api-surface.md
"""

import json
import time
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from pydantic import AnyHttpUrl, Field, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.protocol.agent_api_internal import (
    InternalEventsListResponse,
    InternalSkillsListResponse,
)
from anyagent.protocol.sse import SSEBlock, SSEBlockDecoder
from anyagent.protocol.stage_events import (
    AnyAgentDoneEvent,
    AnyAgentModelStreamEvent,
    StageEvent,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI, OpenAI
    from openai.types.responses.response import Response as OpenAIResponseModel
else:
    OpenAIResponseModel = object


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class AnyAgentSettings(BaseSettings):
    """anyagent Client SDK settings (env-driven)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    base_url: AnyHttpUrl = Field(
        default="http://127.0.0.1:8787",
        alias="ANYAGENT_AGENT_API_BASE_URL",
    )
    api_key: str = Field(alias="AGENT_API_KEY")


# ---------------------------------------------------------------------------
# Shared HTTP helper mixin
# ---------------------------------------------------------------------------

class _Namespace:
    """Base for resource namespaces sharing connection state."""

    __slots__ = ("_base_url", "_api_key", "_http")

    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient | None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._http = http

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}"}

    async def _get(self, path: str, *, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        """Issue GET and return parsed JSON."""
        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, headers=self._headers(), params=params)
        else:
            r = await self._http.get(url, headers=self._headers(), params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, *, timeout: float = 10.0) -> Any:
        """Issue POST (no body) and return parsed JSON."""
        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, headers=self._headers())
        else:
            r = await self._http.post(url, headers=self._headers(), timeout=timeout)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# client.responses — OpenAI Responses API 兼容面
# ---------------------------------------------------------------------------

class Responses(_Namespace):
    """OpenAI Responses API compatible operations (``/v1/responses``)."""

    async def retrieve(self, response_id: str) -> dict[str, Any]:
        """Query response status or final payload via ``GET /v1/responses/{response_id}``."""
        data = await self._get(f"/v1/responses/{response_id}")
        if not isinstance(data, dict):
            raise RuntimeError(f"invalid /v1/responses/{response_id} payload")
        return data

    async def retrieve_typed(self, response_id: str) -> OpenAIResponseModel | None:
        """Retrieve and decode as OpenAI SDK ``Response`` when shape-compatible."""
        from anyagent.protocol.openai_responses import decode_openai_response

        payload = await self.retrieve(response_id)
        return decode_openai_response(payload)

    async def cancel(self, response_id: str) -> dict[str, Any]:
        """Best-effort cancel via ``POST /v1/responses/{response_id}/cancel``."""
        data = await self._post(f"/v1/responses/{response_id}/cancel")
        if not isinstance(data, dict):
            raise RuntimeError(f"invalid /v1/responses/{response_id}/cancel payload")
        return data


# ---------------------------------------------------------------------------
# client.events — 内部观测 / replay
# ---------------------------------------------------------------------------

class Events(_Namespace):
    """Internal event observation and replay (``/internal/events/*``)."""

    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient | None) -> None:
        super().__init__(base_url=base_url, api_key=api_key, http=http)
        self._sse_decoder_factory = SSEBlockDecoder

    async def list(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
    ) -> InternalEventsListResponse:
        """Paginated event list via ``GET /internal/events/list``."""
        data = await self._get(
            "/internal/events/list",
            params={"response_id": response_id, "last_seq": int(last_seq), "limit": int(limit)},
        )
        return InternalEventsListResponse.model_validate(data)

    async def stream(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
    ) -> AsyncIterator[SSEBlock]:
        """SSE stream of persisted events via ``GET /internal/events/stream``."""
        url = f"{self._base_url}/internal/events/stream"
        params: dict[str, Any] = {"response_id": response_id, "last_seq": int(last_seq)}

        async def _iter(client: httpx.AsyncClient) -> AsyncIterator[SSEBlock]:
            decoder = self._sse_decoder_factory()
            async with client.stream("GET", url, headers=self._headers(), params=params, timeout=None) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    for ev in decoder.feed_line(line):
                        yield ev
                for ev in decoder.flush():
                    yield ev

        if self._http is None:
            async with httpx.AsyncClient(timeout=None) as c:
                async for ev in _iter(c):
                    yield ev
            return

        async for ev in _iter(self._http):
            yield ev

    async def stream_typed(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        include_model_events: bool = True,
    ) -> AsyncIterator[StageEvent]:
        """Stream typed ``StageEvent`` union from internal event stream.

        Decodes ``anyagent.*``-prefixed events into typed stage models and wraps
        OpenAI Responses SSE events as ``AnyAgentModelStreamEvent``.
        """
        adapter = TypeAdapter(StageEvent)
        async for blk in self.stream(response_id, last_seq=last_seq):
            seq: int | None = None
            if isinstance(blk.id, str) and blk.id.strip().isdigit():
                try:
                    seq = int(blk.id.strip())
                except Exception:  # noqa: BLE001
                    seq = None

            # [DONE] sentinel
            if blk.event is None and isinstance(blk.data, str) and blk.data.strip() == "[DONE]":
                yield AnyAgentDoneEvent(response_id=response_id, seq=seq, ts_ms=int(time.time() * 1000))
                return

            # anyagent.* stage events
            if isinstance(blk.event, str) and blk.event.startswith("anyagent.") and isinstance(blk.data, str):
                try:
                    payload = json.loads(blk.data)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(payload, dict):
                    continue
                payload.setdefault("type", blk.event)
                payload.setdefault("response_id", response_id)
                payload.setdefault("seq", seq)
                if "ts_ms" not in payload:
                    payload["ts_ms"] = int(time.time() * 1000)
                try:
                    yield adapter.validate_python(payload)
                except Exception:  # noqa: BLE001
                    continue
                continue

            if not include_model_events:
                continue

            # OpenAI Responses SSE events → wrap as AnyAgentModelStreamEvent
            if not isinstance(blk.event, str):
                continue
            if not (blk.event.startswith("response.") or blk.event == "error"):
                continue
            if not isinstance(blk.data, str) or not blk.data.strip():
                continue
            try:
                payload = json.loads(blk.data)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            yield AnyAgentModelStreamEvent(
                response_id=response_id,
                seq=seq,
                sse_event=blk.event,
                payload=payload,
                ts_ms=int(time.time() * 1000),
            )


# ---------------------------------------------------------------------------
# client.skills — 技能发现
# ---------------------------------------------------------------------------

class Skills(_Namespace):
    """Skills discovery (``/internal/skills/list``)."""

    async def list(self, *, agent_id: str = "main") -> InternalSkillsListResponse:
        """List skills visible to an agent via ``GET /internal/skills/list``."""
        data = await self._get("/internal/skills/list", params={"agent_id": agent_id})
        return InternalSkillsListResponse.model_validate(data)


# ---------------------------------------------------------------------------
# AnyAgent — SDK 入口
# ---------------------------------------------------------------------------

class AnyAgent:
    """anyagent Client SDK entry point (resource-namespace pattern).

    Usage::

        client = AnyAgent(api_key="...", base_url="http://127.0.0.1:8787")

        # OpenAI compatible
        resp = await client.responses.retrieve(response_id)
        await client.responses.cancel(response_id)

        # AnyAgent superset
        events = await client.events.list(response_id)
        async for ev in client.events.stream_typed(response_id):
            ...
        skills = await client.skills.list(agent_id="main")

        # Convenience: get OpenAI official SDK clients
        openai_client = client.as_openai_client()
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "http://127.0.0.1:8787",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        shared = {"base_url": base, "api_key": api_key, "http": http}

        self._base_url = base
        self._api_key = api_key

        self.responses = Responses(**shared)
        self.events = Events(**shared)
        self.skills = Skills(**shared)

    def as_openai_client(self) -> "OpenAI":
        """Create an OpenAI official SDK client pointing to this anyagent server."""
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, base_url=f"{self._base_url}/v1")

    def as_async_openai_client(self) -> "AsyncOpenAI":
        """Create an async OpenAI official SDK client pointing to this anyagent server."""
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key, base_url=f"{self._base_url}/v1")


# ---------------------------------------------------------------------------
# Factory (settings-driven)
# ---------------------------------------------------------------------------

def create_anyagent_client(
    *,
    settings: AnyAgentSettings,
    http: httpx.AsyncClient | None = None,
) -> AnyAgent:
    """Create an ``AnyAgent`` client from settings."""
    return AnyAgent(
        api_key=settings.api_key,
        base_url=str(settings.base_url).rstrip("/"),
        http=http,
    )
