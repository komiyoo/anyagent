from __future__ import annotations

"""
anyagent Client SDK — 资源型命名空间入口。

提供 ``AnyAgent`` 入口类，通过子命名空间与缓存属性组织能力：

- ``client.openai`` / ``client.async_openai`` — OpenAI 官方 SDK client（缓存属性）
- ``client.responses`` — AnyAgent 补充的 `/v1/responses/{id}` async helpers
- ``client.events``    — 内部观测 / replay（/internal/events/*）
- ``client.skills``    — 技能发现（/internal/skills/list）
- ``client.admin``     — 管理面 helpers（如 `/admin/storage/health`）

设计决策：docs/architecture/decisions/openai-first-api-surface.md
"""

from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.protocol.agent_api_internal import (
    InternalEventsListResponse,
    InternalEventsReplaySummary,
    InternalSkillsListResponse,
)
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.sse import SSEBlock, SSEBlockDecoder
from anyagent.protocol.stage_events import (
    AnyAgentDoneEvent,
    AnyAgentPromptContextEvent,
    StageEvent,
    decode_stage_event,
    parse_stage_event_seq,
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
# client.responses — AnyAgent optional response helpers
# ---------------------------------------------------------------------------

class Responses(_Namespace):
    """Async helpers for AnyAgent response query/cancel endpoints."""

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

    async def list_typed(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
        include_model_events: bool = True,
    ) -> list[StageEvent]:
        """List persisted internal events and decode them into the typed stage union."""

        listing = await self.list(response_id=response_id, last_seq=last_seq, limit=limit)
        return listing.typed_events(include_model_events=include_model_events)

    async def latest_prompt_context(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
    ) -> AnyAgentPromptContextEvent | None:
        """Find the latest prompt-context event across paginated internal replay pages."""

        cursor = int(last_seq)
        latest: AnyAgentPromptContextEvent | None = None
        while True:
            listing = await self.list(response_id=response_id, last_seq=cursor, limit=limit)
            page_latest = listing.latest_prompt_context()
            if page_latest is not None:
                latest = page_latest
            if listing.done or not listing.events or listing.next_last_seq <= cursor:
                return latest
            cursor = listing.next_last_seq

    async def replay_summary(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
        include_model_events: bool = False,
        max_pages: int = 20,
    ) -> InternalEventsReplaySummary:
        """Build one higher-level replay summary from paginated internal events."""

        cursor = int(last_seq)
        scanned_pages = 0
        page_event_count = 0
        typed_event_count = 0
        latest_prompt_context: AnyAgentPromptContextEvent | None = None
        run_status: str | None = None
        effective_run_status: str | None = None
        done = False
        next_last_seq = cursor

        while scanned_pages < max(1, int(max_pages)):
            listing = await self.list(response_id=response_id, last_seq=cursor, limit=limit)
            scanned_pages += 1
            page_event_count += len(listing.events)
            typed_page = listing.typed_events(include_model_events=include_model_events)
            typed_event_count += len(typed_page)
            page_prompt_context = listing.latest_prompt_context()
            if page_prompt_context is not None:
                latest_prompt_context = page_prompt_context
            run_status = listing.run_status
            effective_run_status = listing.effective_run_status
            done = listing.done
            next_last_seq = listing.next_last_seq
            if listing.done or not listing.events or listing.next_last_seq <= cursor:
                break
            cursor = listing.next_last_seq

        return InternalEventsReplaySummary(
            response_id=response_id,
            requested_last_seq=int(last_seq),
            next_last_seq=next_last_seq,
            page_event_count=page_event_count,
            typed_event_count=typed_event_count,
            scanned_pages=scanned_pages,
            done=done,
            run_status=run_status,
            effective_run_status=effective_run_status,
            prompt_context=latest_prompt_context,
        )

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
        async for blk in self.stream(response_id, last_seq=last_seq):
            decoded = decode_stage_event(
                response_id=response_id,
                event=blk.event,
                data=blk.data,
                seq=parse_stage_event_seq(blk.id),
                include_model_events=include_model_events,
            )
            if decoded is None:
                continue
            yield decoded
            if isinstance(decoded, AnyAgentDoneEvent):
                return


# ---------------------------------------------------------------------------
# client.skills — 技能发现
# ---------------------------------------------------------------------------

class Skills(_Namespace):
    """Skills discovery (``/internal/skills/list``)."""

    async def list(self, *, agent_id: str = "main") -> InternalSkillsListResponse:
        """List skills visible to an agent via ``GET /internal/skills/list``."""
        data = await self._get("/internal/skills/list", params={"agent_id": agent_id})
        return InternalSkillsListResponse.model_validate(data)


class Admin(_Namespace):
    """Admin helpers (`/admin/*`)."""

    async def storage_health(self) -> StorageHealthResponse:
        data = await self._get("/admin/storage/health")
        return StorageHealthResponse.model_validate(data)


# ---------------------------------------------------------------------------
# AnyAgent — SDK 入口
# ---------------------------------------------------------------------------

class AnyAgent:
    """anyagent Client SDK entry point (resource-namespace pattern).

    Usage::

        client = AnyAgent(api_key="...", base_url="http://127.0.0.1:8787")

        # OpenAI-compatible primary path
        resp = client.openai.responses.create(...)
        async_resp = await client.async_openai.responses.create(...)

        # AnyAgent async helpers for optional endpoints
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
        self._openai_client: OpenAI | None = None
        self._async_openai_client: AsyncOpenAI | None = None

        self.responses = Responses(**shared)
        self.events = Events(**shared)
        self.skills = Skills(**shared)
        self.admin = Admin(**shared)

    def _openai_base_url(self) -> str:
        """Return normalized OpenAI SDK base URL for this AnyAgent server."""
        if self._base_url.endswith("/v1"):
            return self._base_url
        return f"{self._base_url}/v1"

    @property
    def openai(self) -> "OpenAI":
        """Return a cached OpenAI SDK sync client bound to this AnyAgent server."""
        if self._openai_client is None:
            self._openai_client = self.as_openai_client()
        return self._openai_client

    @property
    def async_openai(self) -> "AsyncOpenAI":
        """Return a cached OpenAI SDK async client bound to this AnyAgent server."""
        if self._async_openai_client is None:
            self._async_openai_client = self.as_async_openai_client()
        return self._async_openai_client

    def as_openai_client(self) -> "OpenAI":
        """Create a new OpenAI SDK sync client pointing to this AnyAgent server."""
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, base_url=self._openai_base_url())

    def as_async_openai_client(self) -> "AsyncOpenAI":
        """Create a new OpenAI SDK async client pointing to this AnyAgent server."""
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key, base_url=self._openai_base_url())


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
