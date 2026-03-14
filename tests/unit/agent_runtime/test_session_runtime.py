from __future__ import annotations

import asyncio
from dataclasses import dataclass

from anyagent.agent_runtime.session_runtime import (
    apply_session_resume_to_body,
    build_fallback_transcript_items,
    build_next_session_snapshot,
    build_persisted_session_snapshot,
    dedupe_strs,
    persist_session_snapshot,
    prepare_session_request,
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
        prompt_audit={"prompt_cache_key": "cache-1", "fragments": [{"kind": "agents_instructions"}]},
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
        "prompt_context": {
            "prompt_cache_key": "cache-1",
            "fragments": [{"kind": "agents_instructions", "cache_class": "contextual"}],
            "fragment_count": 1,
            "retained_fragment_count": 1,
            "stable_prefix_count": 0,
            "contextual_count": 1,
            "dynamic_count": 0,
            "fragment_kinds": ["agents_instructions"],
            "compacted": False,
        },
    }


@dataclass(slots=True)
class _FakeSessionRecord:
    session_partition_key: str
    agent_id: str
    session_key: str
    snapshot_json: dict
    snapshot_version: int


class _FakeSessionStore:
    def __init__(self) -> None:
        self._records: dict[str, _FakeSessionRecord] = {}

    async def get(self, *, session_partition_key: str) -> _FakeSessionRecord | None:
        return self._records.get(session_partition_key)

    async def create_if_absent(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict,
    ) -> _FakeSessionRecord:
        current = self._records.get(session_partition_key)
        if current is not None:
            return current
        record = _FakeSessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=0,
        )
        self._records[session_partition_key] = record
        return record

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict,
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, _FakeSessionRecord | None]:
        current = self._records.get(session_partition_key)
        if current is None or current.snapshot_version != expected_snapshot_version:
            return False, current
        updated = _FakeSessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=current.snapshot_version + 1,
        )
        self._records[session_partition_key] = updated
        return True, updated


def test_prepare_session_request_bootstraps_and_applies_resume() -> None:
    async def _run() -> None:
        store = _FakeSessionStore()
        prepared = await prepare_session_request(
            session_store=store,
            session_partition_key="main::sess-1",
            agent_id="main",
            session_key="sess-1",
            body={
                "input": [{"role": "user", "content": "hello"}],
                "model": "gpt-4.1-mini",
                "temperature": 0.7,
            },
        )

        assert prepared.previous_snapshot["runtime_config"] == {"model": "gpt-4.1-mini", "temperature": 0.7}
        assert prepared.effective_runtime_config == {"model": "gpt-4.1-mini", "temperature": 0.7}
        assert prepared.effective_body["model"] == "gpt-4.1-mini"
        assert prepared.request_transcript_items == [{"role": "user", "content": "hello"}]

        store._records["main::sess-1"] = _FakeSessionRecord(
            session_partition_key="main::sess-1",
            agent_id="main",
            session_key="sess-1",
            snapshot_json={
                "provider": "openai_responses",
                "runtime_config": {"model": "gpt-4.1-mini", "temperature": 0.3},
                "resume_cursor": {"last_response_id": "resp_prev_1", "fallback_transcript_items": []},
            },
            snapshot_version=1,
        )
        prepared2 = await prepare_session_request(
            session_store=store,
            session_partition_key="main::sess-1",
            agent_id="main",
            session_key="sess-1",
            body={"input": "next turn"},
        )
        assert prepared2.previous_snapshot_version == 1
        assert prepared2.effective_body["previous_response_id"] == "resp_prev_1"
        assert prepared2.effective_runtime_config == {"model": "gpt-4.1-mini", "temperature": 0.3}

    asyncio.run(_run())


def test_persist_session_snapshot_updates_resume_and_fallback_transcript() -> None:
    async def _run() -> None:
        store = _FakeSessionStore()
        await store.create_if_absent(
            session_partition_key="main::sess-2",
            agent_id="main",
            session_key="sess-2",
            snapshot_json={
                "provider": "openai_responses",
                "runtime_config": {"model": "gpt-4.1-mini"},
                "resume_cursor": {"last_response_id": "resp_old", "fallback_transcript_items": [{"role": "user", "content": "turn-1"}]},
            },
        )
        ok, latest = await persist_session_snapshot(
            session_store=store,
            session_partition_key="main::sess-2",
            agent_id="main",
            session_key="sess-2",
            previous_snapshot=store._records["main::sess-2"].snapshot_json,
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini", "temperature": 0.4},
            request_transcript_items=[{"role": "user", "content": "turn-2"}],
            response_id="resp_new",
            effective_status="completed",
            response_json={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "answer-2"}],
                    }
                ]
            },
            last_event_seq=9,
        )
        assert ok is True
        assert latest is not None
        assert latest.snapshot_version == 1
        assert latest.snapshot_json["resume_cursor"]["last_response_id"] == "resp_new"
        assert latest.snapshot_json["resume_cursor"]["fallback_transcript_items"] == [
            {"role": "user", "content": "turn-1"},
            {"role": "user", "content": "turn-2"},
            {"role": "assistant", "content": "answer-2"},
        ]

    asyncio.run(_run())


def test_build_persisted_session_snapshot_honors_resume_override_for_non_completed_status() -> None:
    snapshot = build_persisted_session_snapshot(
        previous_snapshot={
            "provider": "openai_responses",
            "runtime_config": {"model": "gpt-4.1-mini"},
            "resume_cursor": {"last_response_id": "resp_old", "fallback_transcript_items": []},
        },
        runtime_config={"model": "gpt-4.1-mini"},
        request_transcript_items=[{"role": "user", "content": "turn-2"}],
        response_id="resp_run",
        effective_status="errored",
        response_json=None,
        last_event_seq=5,
        resume_last_response_id="resp_override",
    )

    assert snapshot["resume_cursor"]["last_response_id"] == "resp_override"
    assert snapshot["last_run"]["response_id"] == "resp_run"


def test_build_persisted_session_snapshot_carries_prompt_context() -> None:
    snapshot = build_persisted_session_snapshot(
        previous_snapshot={
            "provider": "openai_responses",
            "runtime_config": {"model": "gpt-4.1-mini"},
            "resume_cursor": {"last_response_id": "resp_old", "fallback_transcript_items": []},
        },
        runtime_config={"model": "gpt-4.1-mini"},
        request_transcript_items=[{"role": "user", "content": "turn-2"}],
        response_id="resp_run",
        effective_status="completed",
        response_json={"output": []},
        last_event_seq=5,
        prompt_audit={"prompt_cache_key": "cache-2", "fragments": [{"kind": "environment_context"}]},
    )
    assert snapshot["last_run"]["prompt_context"] == {
        "prompt_cache_key": "cache-2",
        "fragments": [{"kind": "environment_context", "cache_class": "contextual"}],
        "fragment_count": 1,
        "retained_fragment_count": 1,
        "stable_prefix_count": 0,
        "contextual_count": 1,
        "dynamic_count": 0,
        "fragment_kinds": ["environment_context"],
        "compacted": False,
    }
