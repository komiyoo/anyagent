from __future__ import annotations

import asyncio
import json

import pytest

from anyagent.agent_runtime.multiagent_quota import MultiAgentQuota, MultiAgentQuotaExceeded, MultiAgentQuotaSpec
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore
from anyagent.storage.replay import list_internal_events


def test_multiagent_quota_uses_shared_storage_lock_slots() -> None:
    asyncio.run(_run_multiagent_quota_uses_shared_storage_lock_slots())


async def _run_multiagent_quota_uses_shared_storage_lock_slots() -> None:
    shared_lock = InMemoryLeaseLock()
    node_a = MultiAgentQuota(
        lease_lock=shared_lock,
        spec=MultiAgentQuotaSpec(root_response_id="resp_root", max_concurrent_children=2, wait_timeout_ms=0),
    )
    node_b = MultiAgentQuota(
        lease_lock=shared_lock,
        spec=MultiAgentQuotaSpec(root_response_id="resp_root", max_concurrent_children=2, wait_timeout_ms=0),
    )

    first = await node_a.acquire(owner="node-a:child-1")
    second = await node_b.acquire(owner="node-b:child-2")
    with pytest.raises(MultiAgentQuotaExceeded):
        await node_b.acquire(owner="node-b:child-3")

    assert first.key != second.key
    assert await node_a.release(first) is True
    third = await node_b.acquire(owner="node-b:child-3")
    assert third.key == first.key


def test_multiagent_replay_contract_links_parent_and_child_runs() -> None:
    asyncio.run(_run_multiagent_replay_contract_links_parent_and_child_runs())


async def _run_multiagent_replay_contract_links_parent_and_child_runs() -> None:
    run_store = InMemoryRunStore()
    event_store = InMemoryEventStore()
    await run_store.try_create_started(
        response_id="resp_parent",
        session_partition_key="main::thread-1",
        idempotency_key="idem-parent",
        stream=True,
    )
    await run_store.try_create_started(
        response_id="resp_child",
        session_partition_key="researcher::thread-1",
        idempotency_key="idem-child",
        stream=True,
    )

    spawned = {
        "type": "anyagent.subagent.spawned",
        "response_id": "resp_parent",
        "parent_response_id": "resp_parent",
        "child_response_id": "resp_child",
        "agent_id": "researcher",
        "depth": 1,
        "tool_call_id": "call_task_1",
    }
    child_done = {
        "type": "anyagent.subagent.completed",
        "response_id": "resp_parent",
        "parent_response_id": "resp_parent",
        "child_response_id": "resp_child",
        "agent_id": "researcher",
        "depth": 1,
        "tool_call_id": "call_task_1",
    }
    await event_store.append(
        response_id="resp_parent",
        session_partition_key="main::thread-1",
        event="anyagent.subagent.spawned",
        data=json.dumps(spawned),
    )
    await event_store.append(
        response_id="resp_child",
        session_partition_key="researcher::thread-1",
        event="response.completed",
        data=json.dumps({"id": "resp_child", "status": "completed"}),
    )
    await event_store.append(
        response_id="resp_parent",
        session_partition_key="main::thread-1",
        event="anyagent.subagent.completed",
        data=json.dumps(child_done),
    )
    await run_store.set_final(
        response_id="resp_parent",
        status="completed",
        final_response_json={"id": "resp_parent", "status": "completed"},
        error_json=None,
    )
    await run_store.set_final(
        response_id="resp_child",
        status="completed",
        final_response_json={"id": "resp_child", "status": "completed"},
        error_json=None,
    )

    parent_replay = await list_internal_events(
        run_store=run_store,
        event_store=event_store,
        response_id="resp_parent",
        last_seq=0,
    )
    child_replay = await list_internal_events(
        run_store=run_store,
        event_store=event_store,
        response_id="resp_child",
        last_seq=0,
    )

    parent_payloads = [json.loads(item.data) for item in parent_replay.events]
    assert parent_payloads[0]["child_response_id"] == "resp_child"
    assert parent_payloads[0]["parent_response_id"] == "resp_parent"
    assert parent_payloads[0]["tool_call_id"] == "call_task_1"
    assert parent_payloads[1]["child_response_id"] == "resp_child"
    assert child_replay.events[0].event == "response.completed"
    assert json.loads(child_replay.events[0].data)["id"] == "resp_child"
