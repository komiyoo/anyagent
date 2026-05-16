from __future__ import annotations

import json
import logging
import os
import sys
import threading
from typing import Any
from urllib import request

from anyagent.protocol.observability import ObservabilityCategory, ObservabilityEvent, ObservabilityLevel


class ObservabilitySink:
    """Receives typed observability events."""

    def emit(self, event: ObservabilityEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class LoggingSink(ObservabilitySink):
    """Emits JSON events through Python logging."""

    def __init__(self, *, logger_name: str = "anyagent.observability") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, event: ObservabilityEvent) -> None:
        level = getattr(logging, event.level.upper(), logging.INFO)
        payload = event.model_dump(exclude_none=True)
        self._logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class HttpJsonSink(ObservabilitySink):
    """Best-effort newline-free JSON POST sink for third-party collectors."""

    def __init__(self, *, url: str, headers: dict[str, str] | None = None, timeout_s: float = 2.0) -> None:
        self._url = url
        self._headers = dict(headers or {})
        self._timeout_s = timeout_s

    def emit(self, event: ObservabilityEvent) -> None:
        body = event.model_dump_json(exclude_none=True).encode("utf-8")
        headers = {"Content-Type": "application/json", **self._headers}
        req = request.Request(self._url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self._timeout_s) as resp:  # noqa: S310
                resp.read(1)
        except Exception:
            logging.getLogger("anyagent.observability").debug("observability HTTP sink failed", exc_info=True)


class ObservabilityEmitter:
    """Fan-out emitter with typed event validation at the boundary."""

    def __init__(self, sinks: list[ObservabilitySink] | None = None) -> None:
        self._sinks = sinks or [LoggingSink()]
        self._lock = threading.Lock()

    def configure(self, sinks: list[ObservabilitySink]) -> None:
        with self._lock:
            self._sinks = list(sinks)

    def emit(
        self,
        event: str,
        *,
        category: ObservabilityCategory = "runtime",
        level: ObservabilityLevel = "info",
        payload: dict[str, Any] | None = None,
    ) -> ObservabilityEvent:
        item = ObservabilityEvent(event=event, category=category, level=level, payload=dict(payload or {}))
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            sink.emit(item)
        return item


_EMITTER = ObservabilityEmitter()


def get_observability_emitter() -> ObservabilityEmitter:
    return _EMITTER


def emit_observability_event(
    event: str,
    *,
    category: ObservabilityCategory = "runtime",
    level: ObservabilityLevel = "info",
    payload: dict[str, Any] | None = None,
) -> ObservabilityEvent:
    return _EMITTER.emit(event, category=category, level=level, payload=payload)


def configure_observability_from_env() -> None:
    """Configure logging and optional third-party HTTP sink from environment."""

    log_format = os.getenv("ANYAGENT_LOG_FORMAT", "text").strip().lower()
    log_level = os.getenv("ANYAGENT_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, log_level, logging.INFO)
    root = logging.getLogger("anyagent")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        if log_format == "json":
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root.addHandler(handler)

    sinks: list[ObservabilitySink] = [LoggingSink()]
    url = os.getenv("ANYAGENT_OBSERVABILITY_HTTP_URL", "").strip()
    if url:
        headers = _parse_header_env(os.getenv("ANYAGENT_OBSERVABILITY_HTTP_HEADERS", ""))
        sinks.append(HttpJsonSink(url=url, headers=headers))
    _EMITTER.configure(sinks)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts_ms": int(record.created * 1000),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_header_env(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw.strip():
        return headers
    try:
        obj = json.loads(raw)
    except Exception:
        return headers
    if not isinstance(obj, dict):
        return headers
    for key, value in obj.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip():
            headers[key.strip()] = value
    return headers
