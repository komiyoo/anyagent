from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    supports_tools: bool = True
    supports_tool_choice_required: bool = True
    supports_tool_choice_named: bool = True
    supports_temperature: bool = True
    supports_top_p: bool = True
    supports_instructions: bool = True
    supports_streaming_native: bool = False
    supports_parallel_tool_calls: bool = False
    max_output_tokens_cap: int | None = None
    tool_name_max_len: int | None = None


OPENAI_FULL = ProviderCapabilities(
    supports_streaming_native=True,
    supports_parallel_tool_calls=True,
    tool_name_max_len=64,
)
ANTHROPIC_CAPS = ProviderCapabilities(max_output_tokens_cap=8192, tool_name_max_len=128)
GEMINI_CAPS = ProviderCapabilities(max_output_tokens_cap=8192, tool_name_max_len=64)
