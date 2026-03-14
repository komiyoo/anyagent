from __future__ import annotations

from anyagent.protocol.agent_api_internal import InternalEventItem, InternalEventsListResponse


def test_internal_events_list_response_decodes_typed_prompt_context_and_done() -> None:
    listing = InternalEventsListResponse(
        response_id="resp_list_1",
        requested_last_seq=0,
        next_last_seq=14,
        done=True,
        events=[
            InternalEventItem(
                seq=13,
                event="anyagent.prompt.context",
                data='{"response_id":"resp_list_1","prompt_cache_key":"cache_1","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix","stable_id":"agents://main","source_path":"/repo/AGENTS.md","source_hash":"abc"},{"kind":"environment_context","cache_class":"contextual","stable_id":"environment://runtime"}],"ts_ms":333}',
            ),
            InternalEventItem(seq=14, event=None, data="[DONE]"),
        ],
    )

    typed = listing.typed_events(include_model_events=False)

    assert [item.type for item in typed] == ["anyagent.prompt.context", "anyagent.done"]
    assert typed[0].seq == 13
    assert typed[0].prompt_cache_key == "cache_1"
    assert typed[1].seq == 14


def test_internal_events_list_response_latest_prompt_context_returns_latest_match() -> None:
    listing = InternalEventsListResponse(
        response_id="resp_list_2",
        requested_last_seq=0,
        next_last_seq=4,
        done=False,
        events=[
            InternalEventItem(
                seq=1,
                event="anyagent.prompt.context",
                data='{"response_id":"resp_list_2","prompt_cache_key":"cache_old","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix"}],"ts_ms":111}',
            ),
            InternalEventItem(seq=2, event="response.completed", data='{"type":"response.completed","response":{"id":"resp_list_2","object":"response","status":"completed"}}'),
            InternalEventItem(
                seq=3,
                event="anyagent.prompt.context",
                data='{"response_id":"resp_list_2","prompt_cache_key":"cache_new","fragments":[{"kind":"environment_context","cache_class":"contextual"}],"ts_ms":222}',
            ),
        ],
    )

    prompt_context = listing.latest_prompt_context()

    assert prompt_context is not None
    assert prompt_context.seq == 3
    assert prompt_context.prompt_cache_key == "cache_new"
    assert prompt_context.fragments[0].kind == "environment_context"


def test_internal_events_list_response_replay_summary_keeps_prompt_context_and_counts() -> None:
    listing = InternalEventsListResponse(
        response_id="resp_list_3",
        requested_last_seq=0,
        next_last_seq=3,
        done=True,
        effective_run_status="completed",
        events=[
            InternalEventItem(
                seq=1,
                event="anyagent.prompt.context",
                data='{"response_id":"resp_list_3","prompt_cache_key":"cache_summary","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix"}],"fragment_count":1,"retained_fragment_count":1,"stable_prefix_count":1,"contextual_count":0,"dynamic_count":0,"fragment_kinds":["agents_instructions"],"compacted":false,"ts_ms":111}',
            ),
            InternalEventItem(seq=2, event="response.completed", data='{"type":"response.completed","response":{"id":"resp_list_3","object":"response","status":"completed"}}'),
            InternalEventItem(seq=3, event=None, data="[DONE]"),
        ],
    )

    summary = listing.replay_summary(include_model_events=False)

    assert summary.response_id == "resp_list_3"
    assert summary.page_event_count == 3
    assert summary.typed_event_count == 2
    assert summary.done is True
    assert summary.effective_run_status == "completed"
    assert summary.prompt_context is not None
    assert summary.prompt_context.prompt_cache_key == "cache_summary"
