from __future__ import annotations

import json
from typing import Any, TypeAlias

# ---- SSE protocol primitives (SSOT) ----
#
# This module is the single source of truth for:
# - SSE encoding (event/data lines + blank separator)
# - SSE parsing (event/data blocks split by blank lines)
# - Responses API terminal extraction ("response.completed")
#
# Note: We intentionally keep this parser minimal and tolerant:
# - Ignores unknown SSE fields (e.g., id:, retry:, comments)
# - Supports multi-line data blocks (joined with "\n")

SSEEvent: TypeAlias = tuple[str | None, str]


class SSEEventDecoder:
    """
    Incremental SSE block decoder.

    Usage:
    - Feed lines one by one (without trailing newline).
    - When a blank line is seen, one event block is emitted (if any).
    """

    def __init__(self) -> None:
        self._cur_event: str | None = None
        self._cur_data: list[str] = []

    def feed_line(self, line: str) -> list[SSEEvent]:
        if not line.strip():
            return self.flush()

        if line.startswith("event:"):
            self._cur_event = line[len("event:") :].strip() or None
            return []

        if line.startswith("data:"):
            self._cur_data.append(line[len("data:") :].lstrip())
            return []

        return []

    def flush(self) -> list[SSEEvent]:
        if self._cur_event is None and not self._cur_data:
            return []
        ev = (self._cur_event, "\n".join(self._cur_data))
        self._cur_event = None
        self._cur_data = []
        return [ev]


def parse_sse_events(text: str) -> list[SSEEvent]:
    """
    Minimal SSE parser:
    - Split event blocks by blank lines
    - Extract optional `event:` and 1+ `data:` lines (joined by "\\n")
    """
    events: list[SSEEvent] = []
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
            continue
        if line.startswith("data:"):
            cur_data.append(line[len("data:") :].lstrip())
            continue

        # Ignore fields we don't care about (id:, retry:, comments, etc.)
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


def extract_completed_response(events: list[SSEEvent]) -> dict[str, Any] | None:
    """
    Extract the final response payload from a buffered SSE transcript.

    Supports two shapes:
    - {"response": {...}} (OpenAI-style wrapper)
    - {"id": "...", "object": "response", ...} (response object)
    """
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
    """
    Replace response ids in nested payloads so that server-side proxying can
    produce a stable `response_id` even when upstream uses a different id.
    """
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
        return

    if isinstance(payload, list):
        for v in payload:
            normalize_response_id(v, canonical_response_id)
