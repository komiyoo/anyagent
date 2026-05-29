"""Persistence configuration — toggles and thresholds."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PersistenceConfig(BaseModel):
    """Controls what gets persisted and size limits.

    Loaded from workspace config or environment. Defaults are
    production-safe: persist everything with reasonable limits.
    """

    model_config = ConfigDict(extra="forbid")

    persist_rendered_context: bool = Field(
        default=True,
        description="Whether to persist full rendered prompt fragments per response.",
    )
    rendered_context_max_bytes: int = Field(
        default=512 * 1024,
        ge=0,
        description="Max total bytes for rendered context payload. Truncates if exceeded.",
    )
    persist_tool_execution_detail: bool = Field(
        default=True,
        description="Whether to persist full tool input/output payloads.",
    )
    tool_execution_max_bytes: int = Field(
        default=256 * 1024,
        ge=0,
        description="Max bytes per tool execution detail payload.",
    )
    persist_model_request: bool = Field(
        default=True,
        description="Whether to persist the full applied_body sent to model provider.",
    )
    model_request_max_bytes: int = Field(
        default=1024 * 1024,
        ge=0,
        description="Max bytes for model request payload.",
    )
