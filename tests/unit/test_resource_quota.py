from __future__ import annotations

from anyagent.observability import get_observability_emitter
from anyagent.resource_quota import (
    RESOURCE_QUOTA_EVENT,
    channel_for_tool_name,
    emit_resource_exhausted,
    is_quota_exhausted,
    maybe_emit_resource_exhausted,
    reset_resource_exhausted_debounce_for_tests,
)


def test_is_quota_exhausted_status_and_markers() -> None:
    assert is_quota_exhausted(status_code=402) is True
    assert is_quota_exhausted(status_code=429) is True
    assert is_quota_exhausted(status_code=404) is False
    assert is_quota_exhausted(status_code=401) is False
    assert is_quota_exhausted(status_code=403, message="insufficient credits") is True
    assert is_quota_exhausted(status_code=403, message="forbidden") is False
    assert is_quota_exhausted(error_type="RateLimitError", message="rate_limit_exceeded") is True


def test_channel_for_tool_name() -> None:
    assert channel_for_tool_name("core.web_search") == "tavily"
    assert channel_for_tool_name("mcp.amap-maps.maps_geo") == "amap"
    assert channel_for_tool_name("mcp.jina.reader") == "jina"
    assert channel_for_tool_name("mcp.other.foo") == "other"


def test_emit_resource_exhausted_debounces_per_channel(monkeypatch) -> None:
    reset_resource_exhausted_debounce_for_tests()
    monkeypatch.setenv("PROJECT", "lt-anyagent-wks")
    # Fresh CI containers often have monotonic() << debounce window. Using a
    # sentinel of 0.0 for "never emitted" would swallow the first event.
    monkeypatch.setattr("anyagent.resource_quota.time.monotonic", lambda: 12.0)
    seen: list[str] = []

    class _Sink:
        def emit(self, event) -> None:
            seen.append(event.event)

    emitter = get_observability_emitter()
    sink = _Sink()
    emitter.add_sink(sink)
    try:
        first = emit_resource_exhausted("jina", status_code=402, message="credits exceeded")
        second = emit_resource_exhausted("jina", status_code=402, message="credits exceeded again")
        other = maybe_emit_resource_exhausted("tavily", status_code=429, message="rate limit")
        skipped = maybe_emit_resource_exhausted("tavily", status_code=404, message="missing")
    finally:
        emitter.remove_sink(sink)
        reset_resource_exhausted_debounce_for_tests()

    assert first is not None
    assert first.payload["project"] == "lt-anyagent-wks"
    assert first.payload["channel"] == "jina"
    assert second is None
    assert other is not None
    assert skipped is None
    assert seen == [RESOURCE_QUOTA_EVENT, RESOURCE_QUOTA_EVENT]
