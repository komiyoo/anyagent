from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request

from .openai_proxy import _pick_upstream_headers  # noqa: PLC2701
from .settings import Settings


async def create_responses_json(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: dict[str, Any],
    forward_idempotency_key: bool,
) -> tuple[int, dict[str, Any]]:
    url = str(settings.openai_base_url).rstrip("/") + "/responses"
    headers = _pick_upstream_headers(request, settings)
    if not forward_idempotency_key:
        headers.pop("idempotency-key", None)

    r = await client.post(url, headers=headers, json=body, timeout=60.0)
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {"error": {"message": r.text, "type": "upstream_error"}}
    return r.status_code, data


def _parse_sse_events(text: str) -> list[tuple[str | None, str]]:
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
            # ignore comments/fields we don't care about
            continue
    if cur_event is not None or cur_data:
        events.append((cur_event, "\n".join(cur_data)))
    return events


def _extract_completed_response(events: list[tuple[str | None, str]]) -> dict[str, Any] | None:
    for ev, data in reversed(events):
        if ev != "response.completed":
            continue
        try:
            payload = httpx.Response(200, content=data).json()
        except Exception:  # noqa: BLE001
            return None
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            return payload["response"]
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            return payload
        return None
    return None


async def create_responses_sse_events(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: dict[str, Any],
    forward_idempotency_key: bool,
) -> tuple[int, list[tuple[str | None, str]], dict[str, Any] | None, str]:
    url = str(settings.openai_base_url).rstrip("/") + "/responses"
    headers = _pick_upstream_headers(request, settings)
    if not forward_idempotency_key:
        headers.pop("idempotency-key", None)

    async with client.stream("POST", url, headers=headers, json=body, timeout=None) as r:
        raw = await r.aread()
        text = raw.decode("utf-8", errors="replace")
        events = _parse_sse_events(text)
        completed = _extract_completed_response(events)
        return r.status_code, events, completed, text
