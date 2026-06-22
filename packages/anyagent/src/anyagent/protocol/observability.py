from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ObservabilityCategory = Literal["audit", "runtime", "security", "mcp", "server"]
ObservabilityLevel = Literal["debug", "info", "warning", "error"]
TelemetrySource = Literal["run", "event", "stage", "observability", "workspace", "audit"]


class ObservabilityEvent(BaseModel):
    """Typed structure for anyagent structured logs and third-party sinks."""

    model_config = ConfigDict(extra="forbid")

    event: str
    category: ObservabilityCategory = "runtime"
    level: ObservabilityLevel = "info"
    ts_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedTelemetryEvent(BaseModel):
    """Storage-agnostic telemetry row used by Core observability query adapters."""

    model_config = ConfigDict(extra="forbid")

    source: TelemetrySource
    type: str
    ts_ms: int | None = Field(default=None, ge=0)
    response_id: str | None = None
    agent_id: str | None = None
    session_key: str | None = None
    trace_id: str | None = None
    seq: int | None = Field(default=None, ge=1)
    level: ObservabilityLevel | None = None
    category: str | None = None
    status: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_source: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    audit_ref: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
