from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FunctionToolParam(BaseModel):
    """
    OpenAI Responses SDK-compatible function tool schema (single canonical shape).

    Note:
    - This is intentionally aligned to the Python SDK tool param fields.
    - Protocol models use Pydantic as the single source of truth (req: repo convention).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool = True


class ToolChoiceFunctionParam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    name: str


ToolChoice = Literal["none", "auto", "required"] | ToolChoiceFunctionParam


class FunctionCallOutputItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str

