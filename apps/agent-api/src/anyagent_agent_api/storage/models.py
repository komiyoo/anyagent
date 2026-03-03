from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal["started", "completed", "errored"]


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    session_partition_key: str
    idempotency_key: str | None = None
    stream: bool
    status: RunStatus

    last_event_seq: int = Field(default=0, ge=0)
    final_response_json: dict | None = None
    error_json: dict | None = None


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    seq: int = Field(ge=1)
    event: str | None = None
    data: str

