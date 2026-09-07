from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from anyagent.protocol.alerts import AlertChannel, AlertEvent, AlertRule
from anyagent.protocol.agent_api_internal import InternalObservabilityTimelineEvent
from anyagent.resource_quota import current_project_name
from anyagent.server.persistence.telemetry_store import ObservabilityQuery, TelemetryStore


_LOGGER = logging.getLogger(__name__)

# Default event types covered by the built-in error alert rule. These are the
# server / connector failure events emitted via ``emit_observability_event``
# that surface in the telemetry timeline. The list is intentionally generic so
# the rule picks up new error sources without code changes here.
DEFAULT_ERROR_EVENT_TYPES: tuple[str, ...] = (
    "server.response.nonstream.failed",
    "server.response.stream.failed",
    "chatwoot.background.failed",
    "server.unhandled_exception",
)


def default_alert_rules() -> list[AlertRule]:
    return [
        AlertRule(
            rule_id="builtin.loop_warning",
            name="Agent loop warning",
            event_types=["anyagent.agent.loop_warning"],
            severity="warning",
        ),
        AlertRule(
            rule_id="builtin.loop_terminated",
            name="Agent loop terminated",
            event_types=["anyagent.agent.loop_terminated"],
            severity="critical",
        ),
        AlertRule(
            rule_id="builtin.server_error",
            name="Server / connector error",
            event_types=list(DEFAULT_ERROR_EVENT_TYPES),
            severity="error",
        ),
        AlertRule(
            rule_id="builtin.quota_exhausted",
            name="Resource quota exhausted",
            event_types=["provider.quota_exhausted"],
            severity="error",
        ),
    ]


class InMemoryAlertStore:
    def __init__(self, *, rules: list[AlertRule] | None = None, max_events: int = 10_000) -> None:
        self._rules = {rule.rule_id: rule for rule in (rules or default_alert_rules())}
        self._events: dict[str, AlertEvent] = {}
        self._order: list[str] = []
        self._max_events = max(1, max_events)
        self._lock = threading.Lock()

    async def list_rules(self) -> list[AlertRule]:
        with self._lock:
            return list(self._rules.values())

    async def upsert_rule(self, rule: AlertRule) -> AlertRule:
        with self._lock:
            self._rules[rule.rule_id] = rule
        return rule

    async def append_event(self, event: AlertEvent) -> bool:
        with self._lock:
            if event.alert_id in self._events:
                return False
            self._events[event.alert_id] = event
            self._order.append(event.alert_id)
            if len(self._order) > self._max_events:
                for alert_id in self._order[: len(self._order) - self._max_events]:
                    self._events.pop(alert_id, None)
                del self._order[: len(self._order) - self._max_events]
            return True

    async def list_events(self, query: ObservabilityQuery) -> list[AlertEvent]:
        with self._lock:
            events = [self._events[alert_id] for alert_id in reversed(self._order) if alert_id in self._events]
        if query.agent_id is not None:
            events = [event for event in events if event.agent_id == query.agent_id]
        if query.session_key is not None:
            events = [event for event in events if event.session_key == query.session_key]
        if query.response_id is not None:
            events = [event for event in events if event.response_id == query.response_id]
        if query.trace_id is not None:
            events = [event for event in events if event.trace_id == query.trace_id]
        if query.created_after_ms is not None:
            events = [event for event in events if event.ts_ms >= query.created_after_ms]
        if query.created_before_ms is not None:
            events = [event for event in events if event.ts_ms <= query.created_before_ms]
        return events[: query.limit]


@dataclass(slots=True)
class AlertEvaluator:
    telemetry_store: TelemetryStore
    alert_store: InMemoryAlertStore
    interval_s: float = 5.0
    lookback_limit: int = 500

    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event | None = None

    async def evaluate_once(self, query: ObservabilityQuery | None = None) -> list[AlertEvent]:
        rules = [rule for rule in await self.alert_store.list_rules() if rule.enabled]
        if not rules:
            return []
        # Build the union of all rule event types so we can short-circuit events
        # no rule cares about, without hardcoding a specific event-type set.
        all_event_types: set[str] = set()
        for rule in rules:
            all_event_types.update(rule.event_types)
        effective_query = query or ObservabilityQuery(limit=self.lookback_limit)
        timeline = await self.telemetry_store.timeline(effective_query)
        created: list[AlertEvent] = []
        for event in timeline.events:
            if event.type not in all_event_types:
                continue
            for rule in rules:
                if rule.kind != "stage_event" or event.type not in rule.event_types:
                    continue
                alert = _alert_from_timeline_event(rule=rule, event=event)
                if await self.alert_store.append_event(alert):
                    created.append(alert)
                    await self._fanout(rule=rule, alert=alert)
        return created

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="anyagent-alert-evaluator")

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop = None

    async def _run(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await self.evaluate_once()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("alert evaluator tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.1, self.interval_s))
            except asyncio.TimeoutError:
                pass

    async def _fanout(self, *, rule: AlertRule, alert: AlertEvent) -> None:
        for channel in rule.channels:
            if channel.kind != "webhook":
                continue
            try:
                payload = _channel_payload(channel=channel, alert=alert)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(channel.url, headers=channel.headers, json=payload)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("alert webhook fan-out failed: rule_id=%s", rule.rule_id)


def _channel_payload(*, channel: AlertChannel, alert: AlertEvent) -> dict[str, Any]:
    if channel.format == "feishu":
        return {"msg_type": "text", "content": {"text": _feishu_text(alert)}}
    return alert.model_dump(mode="json", exclude_none=True)


def _feishu_text(alert: AlertEvent) -> str:
    payload = alert.payload or {}
    project = payload.get("project")
    if not isinstance(project, str) or not project.strip():
        project = current_project_name()
    channel = payload.get("channel")
    pieces = [
        f"[anyagent alert] {alert.rule_name}",
    ]
    if isinstance(project, str) and project.strip():
        pieces.append(f"project={project.strip()}")
    if isinstance(channel, str) and channel.strip():
        pieces.append(f"channel={channel.strip()}")
    pieces.extend(
        [
            f"event_type={alert.source_event_type or alert.type}",
            f"severity={alert.severity}",
        ]
    )
    if alert.agent_id:
        pieces.append(f"agent_id={alert.agent_id}")
    if alert.session_key:
        pieces.append(f"session_key={alert.session_key}")
    if alert.response_id:
        pieces.append(f"response_id={alert.response_id}")
    status_code = payload.get("status_code")
    if status_code is not None:
        pieces.append(f"status_code={status_code}")
    error_type = payload.get("error_type")
    if error_type:
        pieces.append(f"error_type={error_type}")
    reason = payload.get("reason") or payload.get("message") or payload.get("error_message")
    if isinstance(reason, str) and reason.strip():
        pieces.append(f"error={reason.strip()[:300]}")
    if alert.ts_ms:
        pieces.append(f"ts_ms={alert.ts_ms}")
    return "\n".join(pieces)


def _alert_from_timeline_event(*, rule: AlertRule, event: InternalObservabilityTimelineEvent) -> AlertEvent:
    repeat_count = event.payload.get("repeat_count")
    tool_signature = event.payload.get("tool_signature")
    pieces = [event.type]
    if tool_signature:
        pieces.append(f"tool_signature={tool_signature}")
    if repeat_count is not None:
        pieces.append(f"repeat_count={repeat_count}")
    status_code = event.payload.get("status_code")
    if status_code is not None:
        pieces.append(f"status_code={status_code}")
    error_type = event.payload.get("error_type")
    if error_type:
        pieces.append(f"error_type={error_type}")
    reason = event.payload.get("reason") or event.payload.get("message") or event.payload.get("error_message")
    if isinstance(reason, str) and reason.strip():
        pieces.append(f"error={reason.strip()[:300]}")
    return AlertEvent(
        alert_id=_alert_id(rule=rule, event=event),
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        type=_alert_type_for_event(event.type),
        message="; ".join(pieces),
        ts_ms=event.ts_ms or 0,
        response_id=event.response_id,
        agent_id=event.agent_id,
        session_key=event.session_key,
        trace_id=event.trace_id,
        source_event_type=event.type,
        source_seq=event.seq,
        payload=event.payload,
    )


def _alert_type_for_event(event_type: str) -> str:
    # Collapse the granular server/connector error event types into a stable
    # alert category so downstream consumers can group them.
    if event_type.startswith("server.response."):
        return "server_response"
    if event_type.startswith("chatwoot."):
        return "connector"
    if event_type == "provider.quota_exhausted":
        return "quota"
    if event_type.startswith("server."):
        return "server"
    if event_type.startswith("anyagent.agent."):
        return "agent_loop"
    return event_type


def _alert_id(*, rule: AlertRule, event: InternalObservabilityTimelineEvent) -> str:
    raw = "|".join(
        [
            rule.rule_id,
            event.response_id or "",
            str(event.seq or ""),
            event.type,
            str(event.ts_ms or ""),
        ]
    )
    return "alert_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]
