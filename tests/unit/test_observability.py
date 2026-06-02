from __future__ import annotations

from anyagent.observability import ObservabilityEmitter, ObservabilitySink
from anyagent.protocol.observability import NormalizedTelemetryEvent, ObservabilityEvent
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent
from anyagent.server.persistence.telemetry_store import (
    PostgresTelemetryEventStore,
    _agent_id,
    _session_key,
    _telemetry_event_from_row,
    _telemetry_row,
)


class _MemorySink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[ObservabilityEvent] = []

    def emit(self, event: ObservabilityEvent) -> None:
        self.events.append(event)


def test_observability_emitter_validates_and_fans_out_typed_events() -> None:
    sink = _MemorySink()
    emitter = ObservabilityEmitter([sink])

    event = emitter.emit("tool_execute.done", category="audit", payload={"audit_ref": "aud_1"})

    assert event.event == "tool_execute.done"
    assert event.category == "audit"
    assert event.payload == {"audit_ref": "aud_1"}
    assert sink.events == [event]


def test_observability_event_rejects_unknown_category() -> None:
    try:
        ObservabilityEvent.model_validate({"event": "x", "category": "unknown", "payload": {}})
    except Exception as exc:  # noqa: BLE001
        assert "category" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_postgres_telemetry_store_maps_rows_without_real_database(monkeypatch) -> None:
    class FakeConfig:
        pass

    class FakeEngine:
        pass

    monkeypatch.setattr("anyagent.storage.external.resolve_external_sql_backend_config", lambda **_: FakeConfig())
    monkeypatch.setattr("anyagent.storage.external.create_external_sql_engine", lambda _: FakeEngine())

    store = PostgresTelemetryEventStore(
        postgres_dsn="postgresql://user:pass@localhost:5432/anyagent",
        postgres_schema="public",
        schema_policy="runtime_create",
    )
    event = NormalizedTelemetryEvent(
        source="audit",
        type="tool.policy.denied",
        ts_ms=123,
        response_id="resp",
        agent_id="main",
        session_key="sess",
        trace_id="trace",
        level="warning",
        category="audit",
        status="denied",
        tool_name="exec",
        tool_call_id="call",
        duration_ms=3,
        audit_ref="aud",
        message="denied",
        payload={"policy": "deny"},
    )
    row = _telemetry_row(event)
    round_trip = _telemetry_event_from_row(row)

    assert callable(store._table.insert().values)
    assert row["event_type"] == "tool.policy.denied"
    assert row["payload_json"] == {"policy": "deny"}
    assert round_trip == event


def test_timeline_identity_helpers_fall_back_when_prompt_context_has_no_identity_fields() -> None:
    prompt_context = AnyAgentPromptContextEvent.model_validate(
        {
            "response_id": "resp",
            "type": "anyagent.prompt.context",
            "prompt_cache_key": "cache",
        }
    )

    assert _agent_id(prompt_context, {"agent_id": "main"}, None) == "main"
    assert _session_key(prompt_context, {"session_key": "sess"}, None) == "sess"
