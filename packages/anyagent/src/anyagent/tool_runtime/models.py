from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

ToolCategory = Literal["core", "app", "sandbox", "channel"]


class ToolDefinition(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    category: ToolCategory


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]


class RegisteredTool(BaseModel):
    definition: ToolDefinition
    handler: ToolHandler

    model_config = {"arbitrary_types_allowed": True}

