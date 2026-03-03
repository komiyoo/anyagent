from __future__ import annotations


def encode_sse_event(event: str | None, data: str) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        parts.append(f"data: {line}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")

