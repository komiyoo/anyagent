from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal["started", "completed", "errored"]
WorkspaceState = Literal["active", "checkpointing", "hibernated", "restoring", "deleting", "failed"]


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    session_partition_key: str
    idempotency_key: str | None = None
    stream: bool
    status: RunStatus

    # Unix timestamp in seconds. Used to build minimal OpenAI Response payloads when
    # the final response JSON is not available yet.
    created_at_s: float = Field(default_factory=time, ge=0)

    last_event_seq: int = Field(default=0, ge=0)
    final_response_json: dict | None = None
    error_json: dict | None = None


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    seq: int = Field(ge=1)
    event: str | None = None
    data: str


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_partition_key: str
    agent_id: str
    session_key: str
    snapshot_json: dict[str, Any]
    snapshot_version: int = Field(default=0, ge=0)


class SessionWorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_partition_key: str
    workspace_id: str
    state: WorkspaceState = "active"
    generation: int = Field(default=0, ge=0)

    tenant_id: str | None = None
    sandbox_id: str | None = None
    workspace_root: str = "/workspace"
    snapshot_uri: str | None = None
    snapshot_digest: str | None = None
    snapshot_bytes: int | None = Field(default=None, ge=0)
    last_accessed_at_ms: int | None = Field(default=None, ge=0)
    hot_expires_at_ms: int | None = Field(default=None, ge=0)
    cold_expires_at_ms: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class LeaseLockHandle:
    key: str
    owner: str
