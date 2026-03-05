from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from anyagent_agent_api.storage.inmemory import InMemoryEventStore, InMemoryRunStore
from anyagent_agent_api.storage.rollout import RolloutFileWriter
from anyagent_agent_api.storage.rollout_replay import ReplayFilters, _replay


async def _run_smoke() -> None:
    """Run rollout write-gate + replay cursor smoke checks."""
    root = Path(".runs/_tmp_acceptance_rollout").resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    writer = RolloutFileWriter(root_dir=root)
    run_store = InMemoryRunStore(rollout_writer=writer)
    event_store = InMemoryEventStore(rollout_writer=writer)

    spk = "main::acceptance_smoke"
    rid = "resp_acceptance_1"

    # 1) run started dedupe gate: same semantic record should be blocked on second write.
    created, rec = await run_store.try_create_started(
        response_id=rid,
        session_partition_key=spk,
        idempotency_key="idem_acceptance_1",
        stream=False,
    )
    assert created is True
    created2, _ = await run_store.try_create_started(
        response_id="resp_acceptance_2",
        session_partition_key=spk,
        idempotency_key="idem_acceptance_1",
        stream=False,
    )
    assert created2 is False

    # 2) turn/item/tool_call records (fine-grained observability).
    await writer.append_turn_started(
        session_partition_key=spk,
        response_id=rid,
        turn_index=1,
        previous_response_id=None,
        mode="nonstream",
    )
    call = {"type": "function_call", "call_id": "call_acceptance_1", "name": "core.web_search", "arguments": "{\"q\":\"hello\"}"}
    await writer.append_item_observed(
        session_partition_key=spk,
        response_id=rid,
        turn_index=1,
        item_type="function_call",
        item_id="call_acceptance_1",
        payload=call,
    )
    await writer.append_tool_call_requested(
        session_partition_key=spk,
        response_id=rid,
        turn_index=1,
        tool_call_id="call_acceptance_1",
        tool_name="core.web_search",
        arguments_json=call["arguments"],
        is_system_tool=False,
    )
    await writer.append_tool_call_completed(
        session_partition_key=spk,
        response_id=rid,
        turn_index=1,
        tool_call_id="call_acceptance_1",
        tool_name="core.web_search",
        status="completed",
        output="{\"ok\":true}",
        error=None,
    )
    await writer.append_turn_completed(
        session_partition_key=spk,
        response_id=rid,
        turn_index=1,
        status="completed_with_tool",
        function_call_count=1,
        output_item_count=2,
    )

    # 3) event + replay last_seq cursor.
    seq1 = await event_store.append(
        response_id=rid,
        session_partition_key=rec.session_partition_key,
        event="response.output_item.added",
        data="{\"type\":\"response.output_item.added\"}",
    )
    seq2 = await event_store.append(
        response_id=rid,
        session_partition_key=rec.session_partition_key,
        event="response.completed",
        data="{\"type\":\"response.completed\"}",
    )
    assert (seq1, seq2) == (1, 2)

    await run_store.set_final(
        response_id=rid,
        status="completed",
        final_response_json={"id": rid, "object": "response"},
        error_json=None,
    )

    all_rows = _replay(
        root_dir=root,
        filters=ReplayFilters(
            session_partition_key=spk,
            response_id=rid,
            kinds=set(),
            last_seq=0,
            limit=200,
        ),
        include_fingerprint=False,
    )
    kinds = [r.get("kind") for r in all_rows["records"]]
    assert "turn_started" in kinds and "turn_completed" in kinds
    assert "item_observed" in kinds
    assert "tool_call_requested" in kinds and "tool_call_completed" in kinds

    only_new_events = _replay(
        root_dir=root,
        filters=ReplayFilters(
            session_partition_key=spk,
            response_id=rid,
            kinds={"event_appended"},
            last_seq=1,
            limit=200,
        ),
        include_fingerprint=False,
    )
    assert only_new_events["summary"]["returned"] == 1
    ev = only_new_events["records"][0]
    assert ev.get("kind") == "event_appended"
    assert ev.get("seq") == 2


def main() -> int:
    """Run rollout replay acceptance smoke."""
    asyncio.run(_run_smoke())
    print("ok: acceptance_rollout_replay_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
