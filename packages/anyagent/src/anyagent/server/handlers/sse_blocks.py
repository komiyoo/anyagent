from __future__ import annotations

import json
from typing import Any

from anyagent.protocol.openai_responses import build_minimal_openai_response_json, serialize_completed_response_event_data
from anyagent.protocol.sse import encode_sse_block


def _build_created_sse_block(*, response_id: str, body: dict[str, Any]) -> bytes:
    payload = {
        "type": "response.created",
        "response": build_minimal_openai_response_json(
            response_id=response_id,
            status="in_progress",
            model=str(body.get("model") or "unknown"),
            tools=list(body.get("tools") or []) if isinstance(body.get("tools"), list) else None,
            tool_choice=body.get("tool_choice") if body.get("tool_choice") is not None else "auto",
        ),
    }
    return encode_sse_block(event="response.created", data=json.dumps(payload, ensure_ascii=False), id=None)


def _build_completed_sse_block(payload: dict[str, Any]) -> bytes:
    _response_json, data = serialize_completed_response_event_data(payload)
    return encode_sse_block(event="response.completed", data=data, id=None)


async def _append_done_sentinel(*, state: Any, response_id: str) -> None:
    await state.events.append(response_id=response_id, event=None, data="[DONE]")


def _strip_response_created_blocks(blocks: list[bytes]) -> list[bytes]:
    out: list[bytes] = []
    for block in blocks:
        text = block.decode("utf-8", errors="replace")
        if text.startswith("event: response.created"):
            continue
        out.append(block)
    return out
