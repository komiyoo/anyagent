from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.protocol.stage_events import AnyAgentWorkspaceLifecycleEvent
from anyagent.server.sandbox.workspace_events import JsonlWorkspaceEventStore, WorkspaceEventLog


_EVENT_TYPES = {
    "anyagent.sandbox.workspace.restoring",
    "anyagent.sandbox.workspace.checkpointing",
    "anyagent.sandbox.workspace.hibernated",
}


def test_workspace_event_log_filters_and_caps_events() -> None:
    async def _run() -> None:
        store = WorkspaceEventLog(max_events=2)
        await store.append(_event(session_partition_key="main::a", workspace_id="ws_a", type_="anyagent.sandbox.workspace.checkpointing"))
        await store.append(_event(session_partition_key="main::b", workspace_id="ws_b", type_="anyagent.sandbox.workspace.checkpointing"))
        await store.append(_event(session_partition_key="main::a", workspace_id="ws_a", type_="anyagent.sandbox.workspace.hibernated"))

        all_events = await store.list(limit=10)
        assert [item.seq for item in all_events] == [2, 3]
        filtered = await store.list(session_partition_key="main::a", limit=10)
        assert [item.type for item in filtered] == ["anyagent.sandbox.workspace.hibernated"]

    asyncio.run(_run())


def test_jsonl_workspace_event_store_reloads_events_and_continues_seq(tmp_path: Path) -> None:
    async def _run() -> None:
        first = JsonlWorkspaceEventStore(root_dir=tmp_path)
        await first.append(_event(session_partition_key="main::sess", workspace_id="ws_1", type_="anyagent.sandbox.workspace.checkpointing"))
        await first.append(_event(session_partition_key="main::sess", workspace_id="ws_1", type_="anyagent.sandbox.workspace.hibernated"))

        second = JsonlWorkspaceEventStore(root_dir=tmp_path)
        loaded = await second.list(session_partition_key="main::sess", limit=10)
        assert [item.seq for item in loaded] == [1, 2]
        assert [item.type for item in loaded] == [
            "anyagent.sandbox.workspace.checkpointing",
            "anyagent.sandbox.workspace.hibernated",
        ]

        appended = await second.append(
            _event(session_partition_key="main::sess", workspace_id="ws_1", type_="anyagent.sandbox.workspace.restoring")
        )
        assert appended.seq == 3

    asyncio.run(_run())


def _event(*, session_partition_key: str, workspace_id: str, type_: str) -> AnyAgentWorkspaceLifecycleEvent:
    if type_ not in _EVENT_TYPES:
        raise ValueError(type_)
    return AnyAgentWorkspaceLifecycleEvent(
        type=type_,
        response_id=f"workspace:{session_partition_key}",
        session_partition_key=session_partition_key,
        workspace_id=workspace_id,
    )
