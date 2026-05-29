"""Model request persistence — write and query first model request body.

Write path: called just before the first model provider call, persists the
applied_body (after prompt envelope injection) as a stage event.

Query path: given a response_id, retrieves the last model request event
from the event store.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from anyagent.persistence.config import PersistenceConfig
from anyagent.protocol.stage_events import AnyAgentModelRequestEvent

logger = logging.getLogger("anyagent.persistence.model_request")

EVENT_TYPE = "anyagent.model.request"


class StageSink(Protocol):
    async def __call__(self, event: Any) -> None: ...


class EventStoreReader(Protocol):
    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[Any]: ...


class ModelRequestReplayResponse(BaseModel):
    """API response model for historical model request body replay."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    applied_body: dict[str, Any] | None = None
    prompt_cache_key: str | None = None


class ModelRequestPersistence:
    """Handles writing and querying model request bodies."""

    def __init__(self, *, config: PersistenceConfig | None = None) -> None:
        self._config = config or PersistenceConfig()

    async def persist(
        self,
        *,
        response_id: str,
        applied_body: dict[str, Any],
        prompt_cache_key: str | None = None,
        trace_id: str | None = None,
        stage_sink: StageSink,
    ) -> None:
        if not self._config.persist_model_request:
            return
        if not applied_body:
            return

        event = AnyAgentModelRequestEvent(
            response_id=response_id,
            type=EVENT_TYPE,
            applied_body=applied_body,
            prompt_cache_key=prompt_cache_key,
            trace_id=trace_id,
        )

        try:
            await stage_sink(event)
        except Exception:
            logger.warning("failed to persist model request", exc_info=True)

    async def query(
        self,
        *,
        response_id: str,
        event_store: EventStoreReader,
    ) -> ModelRequestReplayResponse | None:
        events = await event_store.list(response_id=response_id, after_seq=0, limit=500)
        last_data: dict[str, Any] | None = None
        for ev in events:
            data = _parse_event_data(ev.data)
            if not data or data.get("type") != EVENT_TYPE:
                continue
            last_data = data

        if last_data is None:
            return None

        return ModelRequestReplayResponse(
            response_id=response_id,
            applied_body=last_data.get("applied_body"),
            prompt_cache_key=last_data.get("prompt_cache_key"),
        )


def _parse_event_data(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
