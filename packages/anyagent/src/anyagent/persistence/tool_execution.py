"""Tool execution detail persistence — write and query full tool payloads.

Write path: called after each tool execution, persists the complete arguments
and output as a stage event in the event store (best-effort).

Query path: given a response_id, retrieves all detail events from the event
store and returns them as a typed list.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from anyagent.persistence.config import PersistenceConfig
from anyagent.protocol.stage_events import AnyAgentToolExecutionDetailEvent, StageError

logger = logging.getLogger("anyagent.persistence.tool_execution")

EVENT_TYPE = "anyagent.tool.execution.detail"


class StageSink(Protocol):
    async def __call__(self, event: Any) -> None: ...


class EventStoreReader(Protocol):
    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[Any]: ...


class ToolExecutionReplayResponse(BaseModel):
    """API response model for historical tool execution replay."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    tool_executions: list[AnyAgentToolExecutionDetailEvent] = Field(default_factory=list)


class ToolExecutionPersistence:
    """Handles writing and querying full tool execution payloads."""

    def __init__(self, *, config: PersistenceConfig | None = None) -> None:
        self._config = config or PersistenceConfig()

    async def persist(
        self,
        *,
        response_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_json: str,
        output: str | None = None,
        error: dict[str, Any] | None = None,
        status: str = "completed",
        duration_ms: int | None = None,
        output_truncated: bool | None = None,
        audit_ref: str | None = None,
        trace_id: str | None = None,
        stage_sink: StageSink,
    ) -> None:
        if not self._config.persist_tool_execution_detail:
            return

        event = AnyAgentToolExecutionDetailEvent(
            response_id=response_id,
            type=EVENT_TYPE,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_json=arguments_json,
            output=output,
            error=error if error is None else StageError(
                type=error.get("type", "tool_error"),
                message=error.get("message", ""),
                code=error.get("code"),
                retryable=error.get("retryable"),
            ),
            status=status,
            duration_ms=duration_ms,
            output_truncated=output_truncated,
            audit_ref=audit_ref,
            trace_id=trace_id,
        )

        try:
            await stage_sink(event)
        except Exception:
            logger.warning("failed to persist tool execution detail", exc_info=True)

    async def query(
        self,
        *,
        response_id: str,
        event_store: EventStoreReader,
    ) -> list[AnyAgentToolExecutionDetailEvent]:
        events = await event_store.list(response_id=response_id, after_seq=0, limit=500)
        results: list[AnyAgentToolExecutionDetailEvent] = []
        for ev in events:
            data = _parse_event_data(ev.data)
            if not data or data.get("type") != EVENT_TYPE:
                continue
            try:
                results.append(AnyAgentToolExecutionDetailEvent.model_validate(data))
            except Exception:
                continue
        return results


def _parse_event_data(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
