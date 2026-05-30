from __future__ import annotations

import asyncio
import json

from anyagent.observability import FileJsonlReplaySink, get_replay_observability_emitter
from anyagent.protocol.prompt_context import PromptContextAudit, PromptFragmentSummary, RenderedPromptFragment
from anyagent.server.response_persistence import create_distributed_response_persistence_context
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def test_replay_observability_file_sink_emits_from_persisted_prompt_context(tmp_path) -> None:
    asyncio.run(_run_replay_observability_file_sink_emits_from_persisted_prompt_context(tmp_path))


async def _run_replay_observability_file_sink_emits_from_persisted_prompt_context(tmp_path) -> None:
    sink_path = tmp_path / "replay-observability.jsonl"
    emitter = get_replay_observability_emitter()
    emitter.configure([FileJsonlReplaySink(sink_path)])
    storage = StorageRuntime(
        mode="none",
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )
    ctx = create_distributed_response_persistence_context(
        storage=storage,
        session_partition_key="main::session",
        agent_id="main",
        session_key="session",
        previous_snapshot=None,
        previous_snapshot_version=None,
        runtime_config={"observability": {"persist_rendered_context": True}},
        request_transcript_items=[],
        prompt_audit=PromptContextAudit(
            prompt_cache_key="cache-integration",
            fragments=[PromptFragmentSummary(kind="agent", cache_class="stable_prefix", stable_id="agent-main")],
        ),
        prompt_rendered_fragments=[
            RenderedPromptFragment(
                kind="agent",
                role="developer",
                cache_class="stable_prefix",
                stable_id="agent-main",
                rendered_text="Use the repo contract.",
            )
        ],
    )

    try:
        await ctx.append_prompt_context_rendered_event_best_effort("resp_integration_replay")
    finally:
        emitter.configure([])

    events = await storage.event_store.list(response_id="resp_integration_replay", after_seq=0, limit=10)
    rows = [json.loads(line) for line in sink_path.read_text(encoding="utf-8").splitlines()]

    assert [event.event for event in events] == ["anyagent.prompt.context.rendered"]
    assert rows[0]["source"] == "event_store"
    assert rows[0]["category"] == "prompt_context"
    assert rows[0]["event_type"] == "anyagent.prompt.context.rendered"
    assert rows[0]["response_id"] == "resp_integration_replay"
    assert rows[0]["seq"] == 1
    assert rows[0]["payload"]["fragments"][0]["rendered_text"] == "Use the repo contract."
