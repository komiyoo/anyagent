from __future__ import annotations

from anyagent.protocol.session_snapshot import PersistedSessionSnapshot, coerce_persisted_session_snapshot


def test_coerce_persisted_session_snapshot_keeps_typed_prompt_context() -> None:
    snapshot = coerce_persisted_session_snapshot(
        {
            "provider": "openai_responses",
            "runtime_config": {"model": "gpt-4.1-mini"},
            "resume_cursor": {"last_response_id": "resp_1", "fallback_transcript_items": [{"role": "user", "content": "hello"}]},
            "last_run": {
                "response_id": "resp_2",
                "last_event_seq": 7,
                "updated_at_ms": 123,
                "prompt_context": {
                    "prompt_cache_key": "cache_1",
                    "fragments": [{"kind": "environment_context", "cache_class": "contextual"}],
                    "fragment_count": 1,
                    "retained_fragment_count": 1,
                    "stable_prefix_count": 0,
                    "contextual_count": 1,
                    "dynamic_count": 0,
                    "fragment_kinds": ["environment_context"],
                    "compacted": False,
                },
            },
        }
    )

    assert isinstance(snapshot, PersistedSessionSnapshot)
    assert snapshot.resume_cursor.last_response_id == "resp_1"
    assert snapshot.last_run is not None
    assert snapshot.last_run.prompt_context is not None
    assert snapshot.last_run.prompt_context.prompt_cache_key == "cache_1"
    assert snapshot.last_run.prompt_context.fragments[0].kind == "environment_context"
