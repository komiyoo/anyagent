from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Literal
from urllib import request

from pydantic import BaseModel, ConfigDict, Field

from anyagent.env import getenv
from anyagent.protocol.observability import ObservabilityCategory, ObservabilityEvent, ObservabilityLevel


REPLAY_ENVELOPE_SCHEMA_VERSION = "2026-05-30"
REPLAY_EVENT_TYPES = frozenset(
    {
        "anyagent.prompt.context.rendered",
        "anyagent.tool.execution.detail",
        "anyagent.model.request",
    }
)


class ReplayObservabilityEnvelope(BaseModel):
    """Server-internal export envelope for replay-grade observability payloads."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REPLAY_ENVELOPE_SCHEMA_VERSION
    source: Literal["event_store"] = "event_store"
    category: Literal["prompt_context", "tool_execution", "model_request"]
    event_type: str
    response_id: str
    seq: int | None = Field(default=None, ge=1)
    trace_id: str | None = None
    ts_ms: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


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


class ReplayObservabilitySink:
    """Receives server-internal replay observability envelopes."""

    def emit(self, envelope: ReplayObservabilityEnvelope) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def flush(self) -> None:  # pragma: no cover - interface
        return None


class StdoutJsonReplaySink(ReplayObservabilitySink):
    """Writes replay envelopes as newline-delimited JSON to stdout."""

    def emit(self, envelope: ReplayObservabilityEnvelope) -> None:
        print(envelope.model_dump_json(exclude_none=True), file=sys.stdout, flush=True)


class FileJsonlReplaySink(ReplayObservabilitySink):
    """Appends replay envelopes to a JSONL file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path).expanduser()
        self._lock = threading.Lock()

    def emit(self, envelope: ReplayObservabilityEnvelope) -> None:
        line = envelope.model_dump_json(exclude_none=True)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")


class ObservabilityEmitter:
    """Fan-out emitter with typed event validation at the boundary."""

    def __init__(self, sinks: list[ObservabilitySink] | None = None) -> None:
        self._sinks = sinks or [LoggingSink()]
        self._lock = threading.Lock()

    def configure(self, sinks: list[ObservabilitySink]) -> None:
        with self._lock:
            self._sinks = list(sinks)

    def add_sink(self, sink: ObservabilitySink) -> None:
        with self._lock:
            if sink not in self._sinks:
                self._sinks = [*self._sinks, sink]

    def remove_sink(self, sink: ObservabilitySink) -> None:
        with self._lock:
            self._sinks = [item for item in self._sinks if item is not sink]

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


class ReplayObservabilityEmitter:
    """Fan-out emitter for replay-grade observability envelopes."""

    def __init__(self, sinks: list[ReplayObservabilitySink] | None = None) -> None:
        self._sinks = list(sinks or [])
        self._lock = threading.Lock()

    def configure(self, sinks: list[ReplayObservabilitySink]) -> None:
        with self._lock:
            self._sinks = list(sinks)

    def add_sink(self, sink: ReplayObservabilitySink) -> None:
        with self._lock:
            if sink not in self._sinks:
                self._sinks = [*self._sinks, sink]

    def remove_sink(self, sink: ReplayObservabilitySink) -> None:
        with self._lock:
            self._sinks = [item for item in self._sinks if item is not sink]

    def emit(self, envelope: ReplayObservabilityEnvelope) -> ReplayObservabilityEnvelope:
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            sink.emit(envelope)
        return envelope

    def flush(self) -> None:
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            sink.flush()


_EMITTER = ObservabilityEmitter()
_REPLAY_EMITTER = ReplayObservabilityEmitter()


def get_observability_emitter() -> ObservabilityEmitter:
    return _EMITTER


def get_replay_observability_emitter() -> ReplayObservabilityEmitter:
    return _REPLAY_EMITTER


def emit_observability_event(
    event: str,
    *,
    category: ObservabilityCategory = "runtime",
    level: ObservabilityLevel = "info",
    payload: dict[str, Any] | None = None,
) -> ObservabilityEvent:
    return _EMITTER.emit(event, category=category, level=level, payload=payload)


def emit_replay_observability_envelope_from_stage_event(event: Any, *, seq: int | None = None) -> ReplayObservabilityEnvelope | None:
    envelope = build_replay_observability_envelope(event, seq=seq)
    if envelope is None:
        return None
    return _REPLAY_EMITTER.emit(envelope)


def build_replay_observability_envelope(event: Any, *, seq: int | None = None) -> ReplayObservabilityEnvelope | None:
    payload = _event_payload(event)
    event_type = payload.get("type")
    response_id = payload.get("response_id")
    if not isinstance(event_type, str) or event_type not in REPLAY_EVENT_TYPES:
        return None
    if not isinstance(response_id, str) or not response_id.strip():
        return None
    category = _replay_category(event_type)
    if category is None:
        return None
    if seq is None:
        raw_seq = payload.get("seq")
        seq = int(raw_seq) if isinstance(raw_seq, int) and raw_seq >= 1 else None
    trace_id = payload.get("trace_id")
    ts_ms = payload.get("ts_ms")
    return ReplayObservabilityEnvelope(
        category=category,
        event_type=event_type,
        response_id=response_id,
        seq=seq,
        trace_id=trace_id if isinstance(trace_id, str) else None,
        ts_ms=ts_ms if isinstance(ts_ms, int) and ts_ms >= 0 else None,
        payload=redact_replay_payload(payload),
    )


def redact_replay_payload(value: Any) -> Any:
    """Return replay payload data with sensitive keys replaced by placeholders."""

    return _redact_replay_payload(value)


def configure_observability_from_env() -> None:
    """Configure logging and optional third-party HTTP sink from environment."""

    log_format = (getenv("LOG_FORMAT", "text") or "text").strip().lower()
    log_level = (getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper() or "INFO"
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
    url = (getenv("OBSERVABILITY_HTTP_URL") or "").strip()
    if url:
        headers = _parse_header_env(getenv("OBSERVABILITY_HTTP_HEADERS") or "")
        sinks.append(HttpJsonSink(url=url, headers=headers))
    _EMITTER.configure(sinks)

    replay_sinks: list[ReplayObservabilitySink] = []
    replay_stdout = (getenv("REPLAY_OBSERVABILITY_STDOUT") or "").strip().lower()
    if replay_stdout in {"1", "true", "yes", "on"}:
        replay_sinks.append(StdoutJsonReplaySink())
    replay_file = (getenv("REPLAY_OBSERVABILITY_FILE") or "").strip()
    if replay_file:
        replay_sinks.append(FileJsonlReplaySink(replay_file))
    _REPLAY_EMITTER.configure(replay_sinks)


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


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json", exclude_none=True)
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {
            key: value
            for key in ("type", "response_id", "seq", "trace_id", "ts_ms")
            if (value := getattr(event, key, None)) is not None
        }
    return payload if isinstance(payload, dict) else {}


def _replay_category(event_type: str) -> Literal["prompt_context", "tool_execution", "model_request"] | None:
    if event_type == "anyagent.prompt.context.rendered":
        return "prompt_context"
    if event_type == "anyagent.tool.execution.detail":
        return "tool_execution"
    if event_type == "anyagent.model.request":
        return "model_request"
    return None


def _redact_replay_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact_replay_payload(item)
        return out
    if isinstance(value, list):
        return [_redact_replay_payload(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
        "credential",
        "credential_id",
        "auth_ref",
    }


from anyagent.resource_quota import (  # noqa: E402
    RESOURCE_QUOTA_EVENT,
    channel_for_tool_name,
    emit_resource_exhausted,
    is_quota_exhausted,
    maybe_emit_resource_exhausted,
    reset_resource_exhausted_debounce_for_tests,
)

__all__ = [
    "RESOURCE_QUOTA_EVENT",
    "channel_for_tool_name",
    "emit_observability_event",
    "emit_resource_exhausted",
    "is_quota_exhausted",
    "maybe_emit_resource_exhausted",
    "reset_resource_exhausted_debounce_for_tests",
]
