from __future__ import annotations

"""
anyagent Agent API internal endpoints protocol (SSOT).

This module defines the request/response models for Agent API internal endpoints:
- /internal/events/list
- /internal/skills/list

Notes:
- These endpoints are not part of the external OpenAI Responses compatibility surface.
- We still keep them in `anyagent.protocol` so both server and client can share types.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InternalEventItem(BaseModel):
    """One stored SSE block (seq + event + data)."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    event: str | None = None
    data: str


class InternalEventsListResponse(BaseModel):
    """Response model for `GET /internal/events/list`."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    requested_last_seq: int = Field(ge=0)
    next_last_seq: int = Field(ge=0)
    events: list[InternalEventItem] = Field(default_factory=list)
    done: bool
    run_status: str | None = None


class InternalSkillListItem(BaseModel):
    """One skill entry returned by `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    stable_id: str
    name: str
    description: str | None = None
    short_description: str | None = None
    scope: str
    enabled: bool
    requested_tool_names: list[str] = Field(default_factory=list)


class InternalSkillLoadError(BaseModel):
    """One skill load error returned by `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["global", "agent"]
    path: str
    reason: str


class InternalSkillsListResponse(BaseModel):
    """Response model for `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    disabled_paths: list[str] = Field(default_factory=list)
    load_errors: list[InternalSkillLoadError] = Field(default_factory=list)
    skills: list[InternalSkillListItem] = Field(default_factory=list)

