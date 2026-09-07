"""pydantic-ai agent loop adapter.

Public run entry stays `anyagent.agent_runtime.tool_loop.run_tool_loop_*`.
This package owns model mapping, tool wrapping, OTLP, and hooks.
"""

from .models import PydanticAIModelHandle, pydantic_ai_model_id, split_user_prompt_and_history
from .run import run_tool_loop_nonstream, run_tool_loop_stream_buffered, run_tool_loop_stream_live

__all__ = [
    "PydanticAIModelHandle",
    "pydantic_ai_model_id",
    "run_tool_loop_nonstream",
    "run_tool_loop_stream_buffered",
    "run_tool_loop_stream_live",
    "split_user_prompt_and_history",
]
