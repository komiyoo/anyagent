from __future__ import annotations

from anyagent.agent_runtime.session_runtime import (
    apply_session_resume_to_body,
    build_fallback_transcript_items,
    build_next_session_snapshot,
    dedupe_strs,
)


def test_dedupe_strs_preserves_order_and_removes_blanks() -> None:
    assert dedupe_strs([" alpha ", "beta", "", "alpha", " beta ", "gamma"]) == ["alpha", "beta", "gamma"]


def test_apply_session_resume_to_body_injects_previous_response_id() -> None:
    body, previous_response_id = apply_session_resume_to_body(
        body={"input": "hello"},
        session_snapshot={
            "resume_cursor": {
                "last_response_id": "resp_prev_1",
                "fallback_transcript_items": [{"role": "user", "content": "old"}],
            }
        },
    )

    assert previous_response_id == "resp_prev_1"
    assert body["previous_response_id"] == "resp_prev_1"
    assert body["input"] == "hello"


def test_apply_session_resume_to_body_uses_fallback_transcript_when_previous_id_missing() -> None:
    body, previous_response_id = apply_session_resume_to_body(
        body={"input": [{"role": "user", "content": "new question"}]},
        session_snapshot={
            "resume_cursor": {
                "last_response_id": None,
                "fallback_transcript_items": [{"role": "assistant", "content": "old answer"}],
            }
        },
    )

    assert previous_response_id is None
    assert body["input"] == [
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
    ]


def test_build_fallback_transcript_items_appends_request_and_assistant_output() -> None:
    items = build_fallback_transcript_items(
        previous_snapshot={
            "resume_cursor": {
                "fallback_transcript_items": [{"role": "user", "content": "turn-1"}],
            }
        },
        request_input="turn-2",
        response_json={
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "answer-2"},
                        {"type": "ignored", "text": "nope"},
                    ],
                }
            ]
        },
    )

    assert items == [
        {"role": "user", "content": "turn-1"},
        {"role": "user", "content": "turn-2"},
        {"role": "assistant", "content": "answer-2"},
    ]


def test_build_next_session_snapshot_sets_runtime_and_last_run_metadata() -> None:
    snapshot = build_next_session_snapshot(
        previous_snapshot={"resume_cursor": {"fallback_transcript_items": []}},
        runtime_config={"model": "gpt-4o-mini", "temperature": 0.2},
        resume_last_response_id="resp_new",
        fallback_transcript_items=[{"role": "user", "content": "hello"}],
        run_response_id="resp_run",
        last_event_seq=12,
        updated_at_ms=123456,
    )

    assert snapshot["provider"] == "openai_responses"
    assert snapshot["runtime_config"] == {"model": "gpt-4o-mini", "temperature": 0.2}
    assert snapshot["resume_cursor"] == {
        "last_response_id": "resp_new",
        "fallback_transcript_items": [{"role": "user", "content": "hello"}],
    }
    assert snapshot["last_run"] == {
        "response_id": "resp_run",
        "last_event_seq": 12,
        "updated_at_ms": 123456,
    }
