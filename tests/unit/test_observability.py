from __future__ import annotations

from anyagent.observability import ObservabilityEmitter, ObservabilitySink
from anyagent.protocol.observability import ObservabilityEvent


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
