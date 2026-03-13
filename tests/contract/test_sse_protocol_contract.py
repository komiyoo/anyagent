from __future__ import annotations

import json

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
