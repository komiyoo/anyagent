from __future__ import annotations

import asyncio
import json
from typing import Any

from anyagent.observability import ReplayObservabilityEnvelope, ReplayObservabilitySink, get_replay_observability_emitter
from anyagent.protocol.prompt_context import PromptContextAudit, PromptFragmentSummary, RenderedPromptFragment
from anyagent.server.response_persistence import create_distributed_response_persistence_context
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


class _MemoryReplaySink(ReplayObservabilitySink):
    def __init__(self) -> None:
        self.envelopes: list[ReplayObservabilityEnvelope] = []

    def emit(self, envelope: ReplayObservabilityEnvelope) -> None:
        self.envelopes.append(envelope)


def test_response_persistence_context_appends_stage_and_prompt_events() -> None:
    asyncio.run(_run_response_persistence_context_appends_stage_and_prompt_events())


def test_response_persistence_context_respects_rendered_context_config() -> None:
    asyncio.run(_run_response_persistence_context_respects_rendered_context_config())


async def _run_response_persistence_context_appends_stage_and_prompt_events() -> None:
    storage = _storage()
    replay_sink = _MemoryReplaySink()
    replay_emitter = get_replay_observability_emitter()
    replay_emitter.configure([replay_sink])
    ctx = create_distributed_response_persistence_context(
        storage=storage,
        session_partition_key="main::sess",
        agent_id="main",
        session_key="sess",
        previous_snapshot=None,
        previous_snapshot_version=None,
        runtime_config={},
        request_transcript_items=[],
        prompt_audit=PromptContextAudit(
            prompt_cache_key="cache-1",
            fragments=[PromptFragmentSummary(kind="skill", cache_class="stable_prefix", stable_id="s1")],
            fragment_count=1,
            retained_fragment_count=1,
            stable_prefix_count=1,
            fragment_kinds=["skill"],
        ),
        prompt_rendered_fragments=[
            RenderedPromptFragment(
                kind="skill",
                role="developer",
                cache_class="stable_prefix",
                stable_id="s1",
                rendered_text="Use repo rules.",
            )
        ],
    )

    class _StageEvent:
        response_id = "resp_1"
        type = "anyagent.test.event"

        def model_dump_json(self, **_kwargs: Any) -> str:
            return json.dumps({"response_id": self.response_id, "type": self.type, "ok": True})

    try:
        await ctx.stage_sink_best_effort(_StageEvent())
        await ctx.append_prompt_context_event_best_effort("resp_1")
        await ctx.append_prompt_context_rendered_event_best_effort("resp_1")
    finally:
        replay_emitter.configure([])

    events = await storage.event_store.list(response_id="resp_1", after_seq=0, limit=10)
    assert [event.event for event in events] == [
        "anyagent.test.event",
        "anyagent.prompt.context",
        "anyagent.prompt.context.rendered",
    ]
    prompt_payload = json.loads(events[1].data)
    assert prompt_payload["prompt_cache_key"] == "cache-1"
    assert prompt_payload["fragments"][0]["stable_id"] == "s1"
    rendered_payload = json.loads(events[2].data)
    assert rendered_payload["prompt_cache_key"] == "cache-1"
    assert rendered_payload["total_chars"] == len("Use repo rules.")
    assert rendered_payload["fragments"][0]["rendered_text"] == "Use repo rules."
    assert [(item.category, item.response_id, item.seq) for item in replay_sink.envelopes] == [
        ("prompt_context", "resp_1", 3)
    ]


async def _run_response_persistence_context_respects_rendered_context_config() -> None:
    storage = _storage()
    disabled = create_distributed_response_persistence_context(
        storage=storage,
        session_partition_key="main::sess",
        agent_id="main",
        session_key="sess",
        previous_snapshot=None,
        previous_snapshot_version=None,
        runtime_config={"observability": {"persist_rendered_context": False}},
        request_transcript_items=[],
        prompt_audit=PromptContextAudit(prompt_cache_key="cache-disabled"),
        prompt_rendered_fragments=[
            RenderedPromptFragment(kind="skill", role="developer", cache_class="stable_prefix", rendered_text="hidden")
        ],
    )
    await disabled.append_prompt_context_rendered_event_best_effort("resp_disabled")
    assert await storage.event_store.list(response_id="resp_disabled", after_seq=0, limit=10) == []

    bounded = create_distributed_response_persistence_context(
        storage=storage,
        session_partition_key="main::sess",
        agent_id="main",
        session_key="sess",
        previous_snapshot=None,
        previous_snapshot_version=None,
        runtime_config={"observability": {"rendered_context_max_bytes": 180}},
        request_transcript_items=[],
        prompt_audit=PromptContextAudit(prompt_cache_key="cache-bounded"),
        prompt_rendered_fragments=[
            RenderedPromptFragment(kind="skill", role="developer", cache_class="stable_prefix", stable_id="keep", rendered_text="short"),
            RenderedPromptFragment(kind="skill", role="developer", cache_class="contextual", stable_id="drop", rendered_text="x" * 500),
        ],
    )
    await bounded.append_prompt_context_rendered_event_best_effort("resp_bounded")
    events = await storage.event_store.list(response_id="resp_bounded", after_seq=0, limit=10)
    assert [event.event for event in events] == ["anyagent.prompt.context.rendered"]
    rendered_payload = json.loads(events[0].data)
    assert rendered_payload["prompt_cache_key"] == "cache-bounded"
    assert [fragment["stable_id"] for fragment in rendered_payload["fragments"]] == ["keep"]


def test_response_persistence_context_finalizes_run_and_session() -> None:
    asyncio.run(_run_response_persistence_context_finalizes_run_and_session())


async def _run_response_persistence_context_finalizes_run_and_session() -> None:
    storage = _storage()
    await storage.run_store.try_create_started(
        response_id="resp_final",
        session_partition_key="main::sess",
        idempotency_key="idem-final",
        stream=False,
    )
    await storage.session_store.create_if_absent(
        session_partition_key="main::sess",
        agent_id="main",
        session_key="sess",
        snapshot_json={"provider": "openai_responses", "runtime_config": {}, "resume_cursor": {}},
    )
    ctx = create_distributed_response_persistence_context(
        storage=storage,
        session_partition_key="main::sess",
        agent_id="main",
        session_key="sess",
        previous_snapshot={"provider": "openai_responses", "runtime_config": {}, "resume_cursor": {}},
        previous_snapshot_version=0,
        runtime_config={},
        request_transcript_items=[],
        prompt_audit=None,
    )

    await ctx.finalize_nonstream_persisted(
        run_response_id="resp_final",
        response_json={"id": "resp_final", "object": "response", "status": "completed", "model": "gpt-test"},
        effective_status="completed",
        error_json=None,
        resume_last_response_id="resp_final",
    )

    run = await storage.run_store.get("resp_final")
    assert run is not None
    assert run.status == "completed"
    assert run.final_response_json is not None
    assert run.final_response_json["id"] == "resp_final"
    events = await storage.event_store.list(response_id="resp_final", after_seq=0, limit=10)
    assert [event.event for event in events] == ["response.completed", None]
    session = await storage.session_store.get(session_partition_key="main::sess")
    assert session is not None
    assert session.snapshot_json["resume_cursor"]["last_response_id"] == "resp_final"


def _storage() -> StorageRuntime:
    return StorageRuntime(
        mode="none",
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )
