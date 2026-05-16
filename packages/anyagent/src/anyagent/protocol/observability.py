from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ObservabilityCategory = Literal["audit", "runtime", "security", "mcp", "server"]
ObservabilityLevel = Literal["debug", "info", "warning", "error"]


class ObservabilityEvent(BaseModel):
    """Typed structure for anyagent structured logs and third-party sinks."""

    model_config = ConfigDict(extra="forbid")

    event: str
    category: ObservabilityCategory = "runtime"
    level: ObservabilityLevel = "info"
    ts_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    payload: dict[str, Any] = Field(default_factory=dict)

