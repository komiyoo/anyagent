"""Prompt context persistence — write and query rendered fragments.

Write path: called after prompt envelope is built, persists rendered
fragments as a stage event in the event store.

Query path: given a response_id, retrieves the rendered context event
and assembles it into a typed response model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from anyagent.persistence.config import PersistenceConfig
from anyagent.protocol.prompt_context import RenderedPromptFragment
from anyagent.protocol.stage_events import AnyAgentPromptContextRenderedEvent

logger = logging.getLogger("anyagent.persistence.prompt_context")

EVENT_TYPE = "anyagent.prompt.context.rendered"


class StageSink(Protocol):
    async def __call__(self, event: Any) -> None: ...


class EventStoreReader(Protocol):
    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[Any]: ...


class PromptContextReplayResponse(BaseModel):
    """API response model for historical prompt context replay."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    prompt_cache_key: str | None = None
    rendered_fragments: list[RenderedPromptFragment] = Field(default_factory=list)
    total_chars: int = Field(default=0, ge=0)
    truncated: bool = False


class PromptContextPersistence:
    """Handles writing and querying rendered prompt context."""

    def __init__(self, *, config: PersistenceConfig | None = None) -> None:
        self._config = config or PersistenceConfig()

    async def persist(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        rendered_fragments: list[RenderedPromptFragment],
        prompt_cache_key: str | None = None,
        stage_sink: StageSink,
    ) -> None:
        if not self._config.persist_rendered_context:
            return
        if not rendered_fragments:
            return

        fragments_data = [f.model_dump(exclude_none=True) for f in rendered_fragments]
        total_chars = sum(len(f.rendered_text) for f in rendered_fragments)

        truncated = _maybe_truncate(fragments_data, self._config.rendered_context_max_bytes)

        if truncated:
            total_chars = sum(len(f.get("rendered_text", "")) for f in fragments_data)

        event = AnyAgentPromptContextRenderedEvent(
            response_id=response_id,
            type=EVENT_TYPE,
            prompt_cache_key=prompt_cache_key,
            fragments=[RenderedPromptFragment.model_validate(f) for f in fragments_data],
            total_chars=total_chars,
        )

        try:
            await stage_sink(event)
        except Exception:
            logger.warning("failed to persist rendered prompt context", exc_info=True)

    async def query(
        self,
        *,
        response_id: str,
        event_store: EventStoreReader,
    ) -> PromptContextReplayResponse | None:
        events = await event_store.list(response_id=response_id, after_seq=0, limit=100)
        for ev in events:
            data = _parse_event_data(ev.data)
            if not data or data.get("type") != EVENT_TYPE:
                continue
            fragments = [
                RenderedPromptFragment.model_validate(f)
                for f in data.get("fragments", [])
            ]
            return PromptContextReplayResponse(
                response_id=response_id,
                prompt_cache_key=data.get("prompt_cache_key"),
                rendered_fragments=fragments,
                total_chars=data.get("total_chars", 0),
            )
        return None


def _maybe_truncate(fragments: list[dict[str, Any]], max_bytes: int) -> bool:
    """Truncate rendered_text in fragments until total fits within max_bytes."""
    total = sum(len(json.dumps(f, ensure_ascii=False).encode()) for f in fragments)
    if total <= max_bytes:
        return False
    for f in reversed(fragments):
        text = f.get("rendered_text", "")
        if len(text) > 200:
            f["rendered_text"] = text[:100] + f"\n... [truncated {len(text) - 100} chars]"
        total = sum(len(json.dumps(x, ensure_ascii=False).encode()) for x in fragments)
        if total <= max_bytes:
            break
    return True


def _parse_event_data(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
