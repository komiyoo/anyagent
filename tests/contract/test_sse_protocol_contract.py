from __future__ import annotations

import json

from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_error_event import ResponseErrorEvent
from openai.types.responses.response_failed_event import ResponseFailedEvent
from openai.types.responses.response_output_item_added_event import ResponseOutputItemAddedEvent
from openai.types.responses.response_output_item_done_event import ResponseOutputItemDoneEvent
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent
from openai.types.responses.response_text_done_event import ResponseTextDoneEvent

from anyagent.protocol.openai_responses import (
    ensure_completed_response_event_data,
    normalize_completed_response_event_data,
    serialize_completed_response_event_data,
)
from anyagent.protocol.sse import (
    SSEBlockDecoder,
    encode_sse_block,
    extract_completed_response,
    normalize_response_id,
    parse_sse_events,
)


def _message_output_item() -> dict:
    return ResponseOutputMessage(
        id="msg_fixture_1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text="hello", annotations=[])],
    ).model_dump(exclude_none=True, by_alias=True)


def test_encode_and_parse_sse_multiline_contract() -> None:
    block = encode_sse_block(event="response.output_text.delta", data='{"a":1}\n{"b":2}', id="7")
    parsed = parse_sse_events(block.decode("utf-8"))

    assert parsed == [("response.output_text.delta", '{"a":1}\n{"b":2}')]


def test_sse_block_decoder_preserves_id_event_and_done() -> None:
    decoder = SSEBlockDecoder()
    text = (
        "id: 3\n"
        "event: response.completed\n"
        'data: {"type":"response.completed","response":{"id":"resp_old"}}\n'
        "\n"
        "id: 4\n"
        "data: [DONE]\n"
        "\n"
    )

    blocks = []
    for line in text.splitlines():
        blocks.extend(decoder.feed_line(line))
    blocks.extend(decoder.flush())

    assert len(blocks) == 2
    assert blocks[0].id == "3"
    assert blocks[0].event == "response.completed"
    assert json.loads(blocks[0].data)["response"]["id"] == "resp_old"
    assert blocks[1].id == "4"
    assert blocks[1].event is None
    assert blocks[1].data == "[DONE]"


def test_extract_completed_response_supports_wrapped_and_bare_shapes() -> None:
    wrapped = extract_completed_response(
        [
            ("response.created", '{"type":"response.created"}'),
            ("response.completed", '{"type":"response.completed","response":{"id":"resp_wrapped","object":"response"}}'),
        ]
    )
    bare = extract_completed_response(
        [
            ("response.completed", '{"id":"resp_bare","object":"response","status":"completed"}'),
        ]
    )

    assert wrapped == {"id": "resp_wrapped", "object": "response"}
    assert bare == {"id": "resp_bare", "object": "response", "status": "completed"}


def test_normalize_response_id_rewrites_nested_response_shapes() -> None:
    payload = {
        "response_id": "resp_old",
        "response": {
            "id": "resp_old",
            "object": "response",
            "output": [
                {"type": "message", "id": "msg_1"},
                {"type": "tool_result", "response_id": "resp_old"},
            ],
        },
    }

    normalize_response_id(payload, "resp_new")

    assert payload["response_id"] == "resp_new"
    assert payload["response"]["id"] == "resp_new"
    assert payload["response"]["output"][1]["response_id"] == "resp_new"


def test_normalize_completed_response_event_data_rewrites_canonical_id() -> None:
    completed, data = normalize_completed_response_event_data(
        '{"type":"response.completed","response":{"id":"resp_old","object":"response","status":"completed"}}',
        canonical_response_id="resp_new",
    ) or (None, None)

    assert completed == {"id": "resp_new", "object": "response", "status": "completed"}
    assert json.loads(data)["response"]["id"] == "resp_new"


def test_ensure_completed_response_event_data_falls_back_to_minimal_response() -> None:
    completed, data = ensure_completed_response_event_data(
        "not-json",
        response_id="resp_fallback",
        fallback_model="gpt-4.1-mini",
    )

    assert completed["id"] == "resp_fallback"
    assert completed["status"] == "completed"
    assert completed["model"] == "gpt-4.1-mini"
    assert json.loads(data)["response"]["id"] == "resp_fallback"


def test_serialize_completed_response_event_data_wraps_and_normalizes_response() -> None:
    response_json, data = serialize_completed_response_event_data(
        {"id": "resp_old", "object": "response", "status": "completed"},
        canonical_response_id="resp_new",
    )

    assert response_json["id"] == "resp_new"
    payload = json.loads(data)
    assert payload["type"] == "response.completed"
    assert payload["response"]["id"] == "resp_new"


def test_normalize_completed_response_event_data_wraps_bare_response_payload() -> None:
    completed, data = normalize_completed_response_event_data(
        '{"id":"resp_old","object":"response","status":"completed","output":[]}',
        canonical_response_id="resp_new",
    ) or (None, None)

    assert completed == {"id": "resp_new", "object": "response", "status": "completed", "output": []}
    payload = json.loads(data)
    assert payload == {"id": "resp_new", "object": "response", "status": "completed", "output": []}


def test_extract_completed_response_ignores_non_completed_events() -> None:
    completed = extract_completed_response(
        [
            ("response.created", '{"type":"response.created","response":{"id":"resp_1"}}'),
            ("error", '{"error":{"message":"boom"}}'),
            ("response.completed", '{"type":"response.completed","response":{"id":"resp_1","object":"response","status":"completed"}}'),
        ]
    )

    assert completed == {"id": "resp_1", "object": "response", "status": "completed"}


def test_response_created_and_completed_payloads_validate_against_openai_sdk_models() -> None:
    response = Response.model_validate(
        {
            "id": "resp_fixture_1",
            "object": "response",
            "created_at": 123,
            "model": "gpt-4o-mini",
            "output": [],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [],
            "status": "completed",
        }
    )

    created = ResponseCreatedEvent.model_validate(
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": response.model_dump(exclude_none=True, by_alias=True),
        }
    )
    completed = ResponseCompletedEvent.model_validate(
        {
            "type": "response.completed",
            "sequence_number": 1,
            "response": response.model_dump(exclude_none=True, by_alias=True),
        }
    )

    assert created.type == "response.created"
    assert created.response.id == "resp_fixture_1"
    assert completed.type == "response.completed"
    assert completed.response.status == "completed"


def test_response_delta_output_item_and_error_payloads_validate_against_openai_sdk_models() -> None:
    item = _message_output_item()

    delta = ResponseTextDeltaEvent.model_validate(
        {
            "type": "response.output_text.delta",
            "sequence_number": 2,
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "delta": "hel",
            "logprobs": [],
        }
    )
    done = ResponseTextDoneEvent.model_validate(
        {
            "type": "response.output_text.done",
            "sequence_number": 3,
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "text": "hello",
            "logprobs": [],
        }
    )
    added = ResponseOutputItemAddedEvent.model_validate(
        {
            "type": "response.output_item.added",
            "sequence_number": 4,
            "output_index": 0,
            "item": item,
        }
    )
    finished = ResponseOutputItemDoneEvent.model_validate(
        {
            "type": "response.output_item.done",
            "sequence_number": 5,
            "output_index": 0,
            "item": item,
        }
    )
    error = ResponseErrorEvent.model_validate(
        {
            "type": "error",
            "sequence_number": 6,
            "code": "server_error",
            "message": "boom",
            "param": "input",
        }
    )

    assert delta.delta == "hel"
    assert done.text == "hello"
    assert added.item.id == item["id"]
    assert finished.item.content[0].text == "hello"
    assert error.message == "boom"


def test_response_failed_payload_validates_against_openai_sdk_model() -> None:
    response = Response.model_validate(
        {
            "id": "resp_failed_1",
            "object": "response",
            "created_at": 456,
            "model": "gpt-4o-mini",
            "output": [],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [],
            "status": "failed",
            "error": {
                "code": "server_error",
                "message": "provider exploded",
            },
        }
    )
    failed = ResponseFailedEvent.model_validate(
        {
            "type": "response.failed",
            "sequence_number": 7,
            "response": response.model_dump(exclude_none=True, by_alias=True),
        }
    )

    assert failed.type == "response.failed"
    assert failed.response.status == "failed"
    assert failed.response.error is not None
    assert failed.response.error.message == "provider exploded"
