from __future__ import annotations

"""
AnyAgent Agent API client SDK (Python).

This module provides:
- A small HTTP client for AnyAgent Agent API internal endpoints (/internal/*).
- Factory helpers to create OpenAI official SDK clients that talk to AnyAgent's
  OpenAI Responses-compatible surface (POST /v1/responses).
"""

from dataclasses import dataclass
import json
import time
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.protocol.agent_api_internal import (
    InternalEventsListResponse,
    InternalSkillsListResponse,
)
from anyagent.protocol.stage_events import (
    AnyAgentDoneEvent,
    AnyAgentModelStreamEvent,
    StageEvent,
)
from anyagent.protocol.sse import SSEBlock, SSEBlockDecoder
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from openai import AsyncOpenAI, OpenAI


class AnyAgentAgentAPIClientSettings(BaseSettings):
    """AnyAgent Agent API client settings."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    base_url: AnyHttpUrl = Field(default="http://127.0.0.1:8787", alias="ANYAGENT_AGENT_API_BASE_URL")
    api_key: str = Field(alias="AGENT_API_KEY")


@dataclass(slots=True)
class AnyAgentAgentAPIClients:
    """Bundle of OpenAI official SDK clients for AnyAgent."""

    sync: "OpenAI"
    async_: "AsyncOpenAI"


class AnyAgentAgentAPIClient:
    """HTTP client for AnyAgent Agent API (external + internal endpoints)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http
        self._sse_decoder_factory = SSEBlockDecoder

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}"}

    def openai_base_url(self) -> str:
        """Return the OpenAI SDK base_url pointing to this AnyAgent server."""

        return f"{self._base_url}/v1"

    def create_openai_clients(self) -> AnyAgentAgentAPIClients:
        """
        Create OpenAI official SDK clients pointing to AnyAgent Agent API.

        Notes:
        - AnyAgent uses the same auth scheme as OpenAI SDK (`Authorization: Bearer ...`).
          We deliberately pass `api_key=AGENT_API_KEY` so the official SDK sets
          the correct header.
        """

        # Import locally to keep this module usable in environments that only use internal APIs.
        from openai import AsyncOpenAI, OpenAI

        base_url = self.openai_base_url()
        return AnyAgentAgentAPIClients(
            sync=OpenAI(api_key=self._api_key, base_url=base_url),
            async_=AsyncOpenAI(api_key=self._api_key, base_url=base_url),
        )

    async def list_events(
        self,
        *,
        response_id: str,
        last_seq: int = 0,
        limit: int = 200,
    ) -> InternalEventsListResponse:
        """List persisted events for a run, using `GET /internal/events/list`."""

        url = f"{self._base_url}/internal/events/list"
        params = {"response_id": response_id, "last_seq": int(last_seq), "limit": int(limit)}
        if self._http is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=self._headers(), params=params)
        else:
            r = await self._http.get(url, headers=self._headers(), params=params, timeout=10.0)
        r.raise_for_status()
        data: Any = r.json()
        return InternalEventsListResponse.model_validate(data)

    async def stream_events(
        self,
        *,
        response_id: str,
        last_seq: int = 0,
    ) -> AsyncIterator[SSEBlock]:
        """
        Stream persisted events for a run, using `GET /internal/events/stream`.

        Yields SSE blocks with optional `id` (seq) + optional `event` + `data`.
        """

        url = f"{self._base_url}/internal/events/stream"
        params = {"response_id": response_id, "last_seq": int(last_seq)}

        async def _iter_from_client(client: httpx.AsyncClient) -> AsyncIterator[SSEBlock]:
            decoder = self._sse_decoder_factory()
            async with client.stream("GET", url, headers=self._headers(), params=params, timeout=None) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    for ev in decoder.feed_line(line):
                        yield ev
                for ev in decoder.flush():
                    yield ev

        if self._http is None:
            async with httpx.AsyncClient(timeout=None) as client:
                async for ev in _iter_from_client(client):
                    yield ev
            return

        async for ev in _iter_from_client(self._http):
            yield ev

    async def stream_stage_events(
        self,
        *,
        response_id: str,
        last_seq: int = 0,
        include_model_events: bool = True,
    ) -> AsyncIterator[StageEvent]:
        """
        Stream typed stage events from AnyAgent internal event stream.

        Notes:
        - Requires `response_id` (typically used for replay/observability).
        - Emits `anyagent.model.stream_event` wrappers for OpenAI Responses SSE events.
        - Emits AnyAgent stage events (`anyagent.tool.*`, `anyagent.command.*`) when present.
        """

        adapter = TypeAdapter(StageEvent)
        async for blk in self.stream_events(response_id=response_id, last_seq=last_seq):
            seq: int | None = None
            if isinstance(blk.id, str) and blk.id.strip().isdigit():
                try:
                    seq = int(blk.id.strip())
                except Exception:  # noqa: BLE001
                    seq = None

            if blk.event is None and isinstance(blk.data, str) and blk.data.strip() == "[DONE]":
                yield AnyAgentDoneEvent(response_id=response_id, seq=seq, ts_ms=int(time.time() * 1000))
                return

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

            if not isinstance(blk.event, str):
                continue
            # Be conservative: only wrap OpenAI Responses SSE-style events.
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

    async def list_skills(
        self,
        *,
        agent_id: str = "main",
    ) -> InternalSkillsListResponse:
        """List skills visible to an agent, using `GET /internal/skills/list`."""

        url = f"{self._base_url}/internal/skills/list"
        params = {"agent_id": agent_id}
        if self._http is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=self._headers(), params=params)
        else:
            r = await self._http.get(url, headers=self._headers(), params=params, timeout=10.0)
        r.raise_for_status()
        data: Any = r.json()
        return InternalSkillsListResponse.model_validate(data)

    def close(self) -> None:
        """Close the underlying HTTP client if it is owned by the caller."""

        # We intentionally do not close `self._http` here:
        # - Caller might share one httpx.AsyncClient across multiple clients.
        # - Close lifecycle should remain explicit at the integration boundary.
        return


def create_anyagent_agent_api_client(
    *,
    settings: AnyAgentAgentAPIClientSettings,
    http: httpx.AsyncClient | None = None,
) -> AnyAgentAgentAPIClient:
    """Create an AnyAgent Agent API client from settings."""

    return AnyAgentAgentAPIClient(base_url=str(settings.base_url).rstrip("/"), api_key=settings.api_key, http=http)
