"""
Scripted reply protocol (SSOT).

A scripted reply is a deterministic, deployer-authored text answer that the
Agent Server returns instead of invoking the model. It is synthesized into a
normal OpenAI `Response` (one `message` output item with `output_text`) so
consumers and session history cannot tell it apart from a model turn; the only
marker is the `anyagent.response.scripted` stage event.

Boundary: one text reply with optional outbound presentation attributes. No
tool calls, no handoff, no multi-turn.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScriptedReply(BaseModel):
    """Deterministic text reply returned by a scripted reply provider."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="Assistant-visible reply text; becomes the sole output_text.")
    content_type: str | None = Field(default=None, min_length=1, description="Optional outbound message type.")
    content_attributes: dict[str, Any] | None = Field(default=None, description="Optional outbound message attributes.")
    variant_id: str | None = Field(default=None, description="Deployer-side identifier of the matched script/variant.")
    reason: str | None = Field(default=None, description="Why this input was answered deterministically.")

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scripted reply text must not be blank")
        return value
