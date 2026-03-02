from __future__ import annotations

import json
from typing import Any


def parse_sse_events(text: str) -> list[tuple[str | None, str]]:
    """
    极简 SSE parser：按空行分隔 event block，提取 event/data。
    data 多行时用 '\\n' 拼接。
    """
    events: list[tuple[str | None, str]] = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if cur_event is not None or cur_data:
                events.append((cur_event, "\n".join(cur_data)))
            cur_event = None
            cur_data = []
            continue
        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip() or None
        elif line.startswith("data:"):
            cur_data.append(line[len("data:") :].lstrip())
        else:
            continue
    if cur_event is not None or cur_data:
        events.append((cur_event, "\n".join(cur_data)))
    return events


def encode_sse_event(event: str | None, data: str) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        parts.append(f"data: {line}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")


def extract_completed_response(events: list[tuple[str | None, str]]) -> dict[str, Any] | None:
    for ev, data in reversed(events):
        if ev != "response.completed":
            continue
        try:
            payload = json.loads(data)
        except Exception:  # noqa: BLE001
            return None
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            return payload["response"]
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            return payload
        return None
    return None


def normalize_response_id(payload: Any, canonical_response_id: str) -> None:
    if isinstance(payload, dict):
        if payload.get("object") == "response" and isinstance(payload.get("id"), str):
            payload["id"] = canonical_response_id
        if isinstance(payload.get("response_id"), str):
            payload["response_id"] = canonical_response_id
        resp = payload.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("id"), str):
            resp["id"] = canonical_response_id
        for v in payload.values():
            normalize_response_id(v, canonical_response_id)
    elif isinstance(payload, list):
        for v in payload:
            normalize_response_id(v, canonical_response_id)

