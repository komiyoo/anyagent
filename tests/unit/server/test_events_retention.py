from __future__ import annotations

import asyncio

from anyagent.server.events import InMemoryEventStore as InternalInMemoryEventStore
from anyagent.server.events import prune_expired_replay_events
from anyagent.storage.inmemory import InMemoryEventStore as StorageInMemoryEventStore
from anyagent.storage.settings import StorageSettings


def test_storage_event_store_prunes_only_expired_replay_events() -> None:
    asyncio.run(_run_storage_event_store_prunes_only_expired_replay_events())


def test_internal_event_store_prunes_replay_events_with_policy_cutoff() -> None:
    asyncio.run(_run_internal_event_store_prunes_replay_events_with_policy_cutoff())


async def _run_storage_event_store_prunes_only_expired_replay_events() -> None:
    store = StorageInMemoryEventStore()
    await store.append(
        response_id="resp_retention",
        session_partition_key="agent::session",
        event="response.created",
        data="{}",
    )
    await store.append(
        response_id="resp_retention",
        session_partition_key="agent::session",
        event="anyagent.prompt.context.rendered",
        data="{}",
    )
    await store.append(
        response_id="resp_retention",
        session_partition_key="agent::session",
        event="response.completed",
        data="{}",
    )

    deleted = await prune_expired_replay_events(
        store,
        settings=StorageSettings(REPLAY_EVENT_STORE_RETENTION_S=0),
        now_ms=10**15,
    )

    assert deleted == 1
    assert await store.tail_seq(response_id="resp_retention") == 3
    assert [event.seq for event in await store.list(response_id="resp_retention", after_seq=0, limit=10)] == [1, 3]
    assert await store.append(
        response_id="resp_retention",
        session_partition_key="agent::session",
        event="response.done",
        data="[DONE]",
    ) == 4


async def _run_internal_event_store_prunes_replay_events_with_policy_cutoff() -> None:
    store = InternalInMemoryEventStore()
    await store.append(response_id="resp_internal_retention", event="response.created", data="{}")
    await store.append(response_id="resp_internal_retention", event="anyagent.model.request", data="{}")
    await store.append(response_id="resp_internal_retention", event=None, data="[DONE]")

    deleted = await prune_expired_replay_events(
        store,
        settings=StorageSettings(REPLAY_EVENT_STORE_RETENTION_S=0),
        now_ms=10**15,
    )
    events = await store.list_events(response_id="resp_internal_retention", last_seq=0, limit=10)

    assert deleted == 1
    assert events.next_last_seq == 3
    assert [(event.seq, event.event) for event in events.events] == [(1, "response.created"), (3, None)]
