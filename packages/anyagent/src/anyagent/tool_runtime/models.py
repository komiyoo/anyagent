from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

ToolCategory = Literal["core", "app", "sandbox", "channel"]
ToolExposure = Literal["direct", "deferred", "hidden"]
ToolKind = Literal["command"]


class ToolCredentialSpec(BaseModel):
    """Declares a credential requirement for a tool and how it is injected into handler context."""

    ref_kind: str = Field(description="Credential kind to resolve (matches credential.kind).")
    injection_target: str = Field(description="Where to inject, e.g. 'header:Authorization'.")
    format: str = Field(default="{value}", description="Template used to format injected value.")
    required: bool = Field(default=True, description="Whether missing credential should fail tool execution.")
    description: str | None = Field(default=None, description="Human-readable description.")


class ToolDefinition(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    category: ToolCategory
    kind: ToolKind | None = None
    exposure: ToolExposure = "direct"
    credentials: list[ToolCredentialSpec] = Field(default_factory=list)


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]


class RegisteredTool(BaseModel):
    definition: ToolDefinition
    handler: ToolHandler

    model_config = {"arbitrary_types_allowed": True}
