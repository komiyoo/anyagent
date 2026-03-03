from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpawnAgentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = None
    agent_type: str | None = None
    message: str | None = None
    items: list[dict] | None = None
    skills: list[str] | None = None
    fork_context: bool = False

    @model_validator(mode="after")
    def _validate_agent_selector(self) -> "SpawnAgentArgs":
        a = (self.agent_id or "").strip() or None
        t = (self.agent_type or "").strip() or None
        if a is None and t is None:
            raise ValueError("spawn_agent requires agent_id (agent_type is deprecated alias)")
        if a is not None and t is not None and a != t:
            raise ValueError("spawn_agent requires agent_id and agent_type to match when both provided")
        return self


class SpawnAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    agent_id: str
    nickname: str | None = None


class SendInputArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    message: str | None = None
    items: list[dict] | None = None
    interrupt: bool | None = None

    @model_validator(mode="after")
    def _validate_has_input(self) -> "SendInputArgs":
        msg = (self.message or "").strip() or None
        has_items = isinstance(self.items, list) and len(self.items) > 0
        if msg is None and not has_items:
            raise ValueError("send_input requires message or items")
        return self


class SendInputResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: str


class WaitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1)
    timeout_ms: int = Field(default=30_000, ge=10_000, le=3_600_000)


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["queued", "running", "completed", "failed", "closed"]
    message: str | None = None


class WaitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents_states: dict[str, AgentState]
    timed_out: bool


class CloseAgentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class CloseAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


class ResumeAgentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class ResumeAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
