from __future__ import annotations

"""
Tool Runtime HTTP API models.

SSOT 位于 `anyagent.protocol.tool_runtime`。
此模块仅保留 app 内部 import 兼容路径，避免重复定义协议结构。
"""

from anyagent.protocol.tool_runtime import (
    AuthRef,
    ChannelContext,
    ExecuteMeta,
    ExecuteRequest,
    ExecuteResponse,
    ExecuteResponseCancelled,
    ExecuteResponseCompleted,
    ExecuteResponseError,
    ManifestDecision,
    ManifestRequest,
    ManifestResponse,
    PolicyHint,
    RequesterContext,
    ToolContext,
    ToolError,
    TraceContext,
)

# Backward-compatible alias for the old local name.
Context = ToolContext

__all__ = [
    "AuthRef",
    "ChannelContext",
    "Context",
    "ExecuteMeta",
    "ExecuteRequest",
    "ExecuteResponse",
    "ExecuteResponseCancelled",
    "ExecuteResponseCompleted",
    "ExecuteResponseError",
    "ManifestDecision",
    "ManifestRequest",
    "ManifestResponse",
    "PolicyHint",
    "RequesterContext",
    "ToolContext",
    "ToolError",
    "TraceContext",
]
