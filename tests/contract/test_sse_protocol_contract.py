from __future__ import annotations

import json

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
