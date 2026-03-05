from __future__ import annotations

"""Protocol models for optional `/v1/responses/{id}` query/cancel endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


AnyAgentResponseStatus = Literal["in_progress", "completed", "failed", "cancelled"]


class AnyAgentResponseError(BaseModel):
    """One response-level error object for optional query/cancel payloads."""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    code: str | None = None


class AnyAgentResponseStatusPayload(BaseModel):
    """Minimal response payload for optional query/cancel endpoints."""

    model_config = ConfigDict(extra="forbid")

    id: str
    object: Literal["response"] = "response"
    status: AnyAgentResponseStatus
    error: AnyAgentResponseError | None = None

