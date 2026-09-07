"""Hosted loop contract: manifest/execute helpers plus pydantic-ai run entry."""

from .loop import (
    run_tool_loop_nonstream,
    run_tool_loop_stream_buffered,
    run_tool_loop_stream_live,
)
from .tool_execution import (
    ManifestRefresher,
    ManifestResolver,
    StageEventSink,
    SystemToolExecutor,
    resolve_manifest,
    resolve_manifest_with_mcp,
)

__all__ = [
    "ManifestRefresher",
    "ManifestResolver",
    "StageEventSink",
    "SystemToolExecutor",
    "resolve_manifest",
    "resolve_manifest_with_mcp",
    "run_tool_loop_nonstream",
    "run_tool_loop_stream_buffered",
    "run_tool_loop_stream_live",
]
