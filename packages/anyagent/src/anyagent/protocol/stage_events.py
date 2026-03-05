from __future__ import annotations

"""
Stage events protocol (SSOT).

These events are produced by anyagent Agent API (persisted into Event Store) and
consumed by anyagent client SDKs to provide 1-level fine-grained runtime progress:
- model stream events (wrapped)
- tool planned/result
- command planned/result (derived for command-like tools)
"""

import hashlib
import json
import re
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


class StagePayloadSummary(BaseModel):
    """A safe summary of a potentially sensitive payload."""

    model_config = ConfigDict(extra="forbid")

    bytes: int = Field(ge=0)
    sha256: str
    preview: str | None = None
    preview_truncated: bool = False


def _sha256_utf8_str(s: str) -> tuple[int, str]:
    """Return (utf8_bytes, sha256_hex) without allocating one huge bytes object."""

    h = hashlib.sha256()
    total = 0
    # Chunk on Python unicode chars; each chunk encodes independently.
    for i in range(0, len(s), 8192):
        b = s[i : i + 8192].encode("utf-8", errors="replace")
        total += len(b)
        h.update(b)
    return total, h.hexdigest()


def _sha256_byteslike(b: bytes | bytearray | memoryview) -> tuple[int, str]:
    """Return (bytes_len, sha256_hex) without copying large buffers."""

    h = hashlib.sha256()
    mv = b if isinstance(b, memoryview) else memoryview(b)
    total = len(mv)
    for i in range(0, total, 8192):
        h.update(mv[i : i + 8192])
    return total, h.hexdigest()


def _safe_json_dumps(value: Any, *, sort_keys: bool) -> str:
    """Best-effort JSON dump that never raises."""

    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)
    except Exception:  # noqa: BLE001
        pass
    try:
        # `default=repr` makes many non-JSON values serializable without leaking raw content.
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys, default=repr)
    except Exception:  # noqa: BLE001
        return json.dumps({"repr": repr(value)}, ensure_ascii=False, separators=(",", ":"))


_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization\\s*:\\s*bearer|bearer\\s+[A-Za-z0-9\\-_=]{8,}|sk-[A-Za-z0-9_-]{8,})"
)


def summarize_payload(value: Any, *, preview_chars: int = 256, max_object_keys: int = 32) -> StagePayloadSummary:
    """
    Summarize a potentially sensitive payload without leaking raw contents.

    Rules:
    - Never return the raw payload in the summary.
    - Only return size/hash, and (optionally) a keys-only preview for JSON objects.
    """

    preview: str | None = None
    preview_truncated = False

    raw_bytes: bytes | bytearray | memoryview | None = None
    raw_text: str = ""

    if isinstance(value, dict):
        sort_keys = all(isinstance(k, str) for k in value.keys())
        raw_text = _safe_json_dumps(value, sort_keys=sort_keys)
        keys = sorted([k for k in value.keys() if isinstance(k, str)])[: max_object_keys]
        preview = ("object keys: " + ",".join(keys)) if keys else None
    elif isinstance(value, list):
        raw_text = _safe_json_dumps(value, sort_keys=False)
    elif isinstance(value, str):
        # Hash the string as-is; do not canonicalize JSON as it changes the bytes.
        raw_text = value
        try:
            obj = json.loads(value)
        except Exception:  # noqa: BLE001
            obj = None
        if isinstance(obj, dict):
            keys = sorted([k for k in obj.keys() if isinstance(k, str)])[: max_object_keys]
            preview = ("object keys: " + ",".join(keys)) if keys else None
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw_bytes = value
    elif value is None:
        raw_text = ""
    else:
        # Keep it predictable and safe: hash the repr, do not preview.
        raw_text = repr(value)

    if isinstance(preview, str) and len(preview) > preview_chars:
        preview = preview[:preview_chars]
        preview_truncated = True

    if raw_bytes is not None:
        size, digest = _sha256_byteslike(raw_bytes)
    else:
        size, digest = _sha256_utf8_str(raw_text)
    return StagePayloadSummary(
        bytes=size,
        sha256=digest,
        preview=preview,
        preview_truncated=preview_truncated,
    )


def summarize_command(command: str, *, preview_chars: int = 256) -> StagePayloadSummary:
    """
    Summarize a command string with a safe preview for observability.

    Rules:
    - If the command looks like it contains secrets, do not include preview.
    - Otherwise include a truncated preview (first N chars).
    """

    raw = command if isinstance(command, str) else str(command)
    size, digest = _sha256_utf8_str(raw)

    preview: str | None = None
    preview_truncated = False
    if raw and not _SENSITIVE_TEXT_RE.search(raw):
        preview = raw[:preview_chars]
        preview_truncated = len(raw) > preview_chars

    return StagePayloadSummary(bytes=size, sha256=digest, preview=preview, preview_truncated=preview_truncated)


class StageError(BaseModel):
    """A machine-readable error for stage events."""

    model_config = ConfigDict(extra="forbid")

    type: str
    code: str | None = None
    message: str
    retryable: bool | None = None


class StageEventBase(BaseModel):
    """Base fields for all stage events."""

    model_config = ConfigDict(extra="forbid")

    type: str
    response_id: str
    seq: int | None = Field(default=None, ge=1)
    trace_id: str | None = None
    ts_ms: int | None = Field(default=None, ge=0)


class AnyAgentModelStreamEvent(StageEventBase):
    """Wrap one OpenAI Responses stream event JSON payload."""

    type: Literal["anyagent.model.stream_event"] = "anyagent.model.stream_event"
    sse_event: str | None = None
    payload: dict[str, Any]


class AnyAgentToolPlannedEvent(StageEventBase):
    """A tool call has been planned (requested by the model)."""

    type: Literal["anyagent.tool.planned"] = "anyagent.tool.planned"
    tool_call_id: str
    tool_name: str
    arguments: StagePayloadSummary


class AnyAgentToolResultMeta(BaseModel):
    """Execution metadata for a tool call."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int | None = Field(default=None, ge=0)
    output_truncated: bool | None = None
    audit_ref: str | None = None


class AnyAgentToolResultEvent(StageEventBase):
    """A tool call has finished executing."""

    type: Literal["anyagent.tool.result"] = "anyagent.tool.result"
    tool_call_id: str
    tool_name: str
    status: str
    meta: AnyAgentToolResultMeta = Field(default_factory=AnyAgentToolResultMeta)
    output: StagePayloadSummary | None = None
    error: StageError | None = None


class AnyAgentCommandPlannedEvent(StageEventBase):
    """A command has been planned (derived from a command-like tool call)."""

    type: Literal["anyagent.command.planned"] = "anyagent.command.planned"
    command: StagePayloadSummary
    workdir: str | None = None
    timeout_ms: int | None = Field(default=None, ge=0)
    source_tool_call_id: str
    source_tool_name: str


class AnyAgentCommandResultEvent(StageEventBase):
    """A command has finished executing (derived from a command-like tool call)."""

    type: Literal["anyagent.command.result"] = "anyagent.command.result"
    exit_code: int | None = None
    stdout: StagePayloadSummary | None = None
    stderr: StagePayloadSummary | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    source_tool_call_id: str
    source_tool_name: str


class AnyAgentDoneEvent(StageEventBase):
    """Terminal stage event emitted when `[DONE]` is observed."""

    type: Literal["anyagent.done"] = "anyagent.done"


StageEvent: TypeAlias = Annotated[
    AnyAgentModelStreamEvent
    | AnyAgentToolPlannedEvent
    | AnyAgentToolResultEvent
    | AnyAgentCommandPlannedEvent
    | AnyAgentCommandResultEvent
    | AnyAgentDoneEvent,
    Field(discriminator="type"),
]
