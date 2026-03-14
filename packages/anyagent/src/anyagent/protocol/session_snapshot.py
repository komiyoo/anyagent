from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from anyagent.protocol.prompt_context import PromptContextAudit


class SessionResumeCursor(BaseModel):
    """Typed resume cursor persisted inside one session snapshot."""

    model_config = ConfigDict(extra="allow")

    last_response_id: str | None = None
    fallback_transcript_items: list[dict[str, Any]] = Field(default_factory=list)


class SessionLastRun(BaseModel):
    """Typed last-run metadata persisted inside one session snapshot."""

    model_config = ConfigDict(extra="allow")

    response_id: str | None = None
    last_event_seq: int = Field(default=0, ge=0)
    updated_at_ms: int | None = Field(default=None, ge=0)
    prompt_context: PromptContextAudit | None = None


class PersistedSessionSnapshot(BaseModel):
    """Typed persisted session snapshot used for resume and replay."""

    model_config = ConfigDict(extra="allow")

    provider: str = "openai_responses"
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    resume_cursor: SessionResumeCursor = Field(default_factory=SessionResumeCursor)
    last_run: SessionLastRun | None = None


def coerce_persisted_session_snapshot(snapshot: dict[str, Any] | None) -> PersistedSessionSnapshot:
    """Validate one persisted snapshot dict into the typed session model."""

    if not isinstance(snapshot, dict):
        return PersistedSessionSnapshot()
    return PersistedSessionSnapshot.model_validate(snapshot)
