from __future__ import annotations

import asyncio
import json
from typing import Any

from anyagent.protocol.prompt_context import PromptContextAudit, PromptFragmentSummary
from anyagent.server.response_persistence import create_distributed_response_persistence_context
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def test_response_persistence_context_appends_stage_and_prompt_events() -> None:
    asyncio.run(_run_response_persistence_context_appends_stage_and_prompt_events())


async def _run_response_persistence_context_appends_stage_and_prompt_events() -> None:
    storage = _storage()
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
    )

    class _StageEvent:
        response_id = "resp_1"
        type = "anyagent.test.event"

        def model_dump_json(self, **_kwargs: Any) -> str:
            return json.dumps({"response_id": self.response_id, "type": self.type, "ok": True})

    await ctx.stage_sink_best_effort(_StageEvent())
    await ctx.append_prompt_context_event_best_effort("resp_1")

    events = await storage.event_store.list(response_id="resp_1", after_seq=0, limit=10)
    assert [event.event for event in events] == ["anyagent.test.event", "anyagent.prompt.context"]
    prompt_payload = json.loads(events[1].data)
    assert prompt_payload["prompt_cache_key"] == "cache-1"
    assert prompt_payload["fragments"][0]["stable_id"] == "s1"


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
