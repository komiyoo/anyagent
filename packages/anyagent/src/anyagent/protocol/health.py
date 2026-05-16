from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Response model for `GET /healthz`."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    workspace: str
    agent_ids: list[str] = Field(default_factory=list)
