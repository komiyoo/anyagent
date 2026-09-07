from __future__ import annotations

import os
import threading
import time
from typing import Any

from anyagent.observability import emit_observability_event
from anyagent.protocol.observability import ObservabilityEvent


RESOURCE_QUOTA_EVENT = "provider.quota_exhausted"
RESOURCE_QUOTA_DEBOUNCE_S = 300.0
_QUOTA_STATUS_CODES = frozenset({402, 429})
_QUOTA_MARKERS = (
    "quota",
    "credit",
    "credits",
    "rate limit",
    "rate_limit",
    "too many requests",
    "insufficient",
    "payment required",
    "balance",
)

_last_emit_at: dict[str, float] = {}
_lock = threading.Lock()


def current_project_name() -> str:
    return (os.getenv("PROJECT") or "").strip()


def is_quota_exhausted(
    *,
    status_code: int | None = None,
    message: str | None = None,
    error_type: str | None = None,
) -> bool:
    if status_code in _QUOTA_STATUS_CODES:
        return True
    blob = f"{error_type or ''} {message or ''}".lower()
    if not blob.strip():
        return False
    if status_code == 403 and any(marker in blob for marker in _QUOTA_MARKERS):
        return True
    return any(
        marker in blob
        for marker in ("rate_limit", "insufficient_quota", "quota exceeded", "credits exceeded", "credit exhausted")
    )


def channel_for_tool_name(tool_name: str) -> str:
    lowered = tool_name.strip().lower()
    if lowered == "core.web_search" or "tavily" in lowered:
        return "tavily"
    if "amap" in lowered:
        return "amap"
    if "jina" in lowered:
        return "jina"
    if lowered.startswith("mcp."):
        parts = lowered.split(".")
        return parts[1] if len(parts) > 1 and parts[1] else "mcp"
    head = lowered.split(".", 1)[0]
    return head or "unknown"


def emit_resource_exhausted(
    channel: str,
    *,
    status_code: int | None = None,
    message: str | None = None,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ObservabilityEvent | None:
    """Emit a quota-exhausted observability event for the alert webhook pipeline.

    Debounced per channel so a tight retry loop does not flood Feishu.
    """

    name = channel.strip() or "unknown"
    now = time.monotonic()
    with _lock:
        last = _last_emit_at.get(name)
        # Missing keys must not use 0.0: fresh CI containers often have
        # time.monotonic() < RESOURCE_QUOTA_DEBOUNCE_S, which would drop the
        # first emit after reset.
        if last is not None and now - last < RESOURCE_QUOTA_DEBOUNCE_S:
            return None
        _last_emit_at[name] = now

    payload: dict[str, Any] = {
        "channel": name,
        "error_type": (error_type or "quota_exhausted").strip() or "quota_exhausted",
    }
    project = current_project_name()
    if project:
        payload["project"] = project
    if status_code is not None:
        payload["status_code"] = int(status_code)
    if isinstance(message, str) and message.strip():
        payload["message"] = message.strip()[:300]
    if extra:
        for key, value in extra.items():
            if key in payload or value is None:
                continue
            payload[key] = value
    return emit_observability_event(
        RESOURCE_QUOTA_EVENT,
        category="server",
        level="error",
        payload=payload,
    )


def maybe_emit_resource_exhausted(
    channel: str,
    *,
    status_code: int | None = None,
    message: str | None = None,
    error_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ObservabilityEvent | None:
    if not is_quota_exhausted(status_code=status_code, message=message, error_type=error_type):
        return None
    return emit_resource_exhausted(
        channel,
        status_code=status_code,
        message=message,
        error_type=error_type,
        extra=extra,
    )


def reset_resource_exhausted_debounce_for_tests() -> None:
    with _lock:
        _last_emit_at.clear()
