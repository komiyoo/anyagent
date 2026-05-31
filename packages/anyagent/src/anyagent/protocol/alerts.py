from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AlertSeverity = Literal["info", "warning", "critical"]
AlertRuleKind = Literal["stage_event"]
AlertEventStatus = Literal["active", "resolved"]
AlertChannelKind = Literal["webhook"]


class AlertChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AlertChannelKind = "webhook"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    name: str
    enabled: bool = True
    kind: AlertRuleKind = "stage_event"
    event_types: list[str] = Field(default_factory=list)
    severity: AlertSeverity = "warning"
    channels: list[AlertChannel] = Field(default_factory=list)


class AlertEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str
    rule_id: str
    rule_name: str
    status: AlertEventStatus = "active"
    severity: AlertSeverity
    type: str
    message: str
    ts_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    response_id: str | None = None
    agent_id: str | None = None
    session_key: str | None = None
    trace_id: str | None = None
    source_event_type: str | None = None
    source_seq: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class AlertEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = None
    session_key: str | None = None
    response_id: str | None = None
    trace_id: str | None = None
    alerts: list[AlertEvent] = Field(default_factory=list)


class AlertRulesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[AlertRule] = Field(default_factory=list)
