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
import time
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics
from anyagent.protocol.prompt_context import (
    PromptContextAudit,
    PromptFragmentSummary,
    RenderedPromptFragment,
    build_prompt_context_audit,
    compact_prompt_fragments,
)


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


class AnyAgentToolExecutionDetailEvent(StageEventBase):
    """Full tool execution payload for historical replay — supplements planned/result summaries."""

    type: Literal["anyagent.tool.execution.detail"] = "anyagent.tool.execution.detail"
    tool_call_id: str
    tool_name: str
    arguments_json: str = ""
    output: str | None = None
    error: StageError | None = None
    status: str
    duration_ms: int | None = Field(default=None, ge=0)
    output_truncated: bool | None = None
    audit_ref: str | None = None


class AnyAgentModelRequestEvent(StageEventBase):
    """First model request body sent to the model provider, persisted for historical replay."""

    type: Literal["anyagent.model.request"] = "anyagent.model.request"
    applied_body: dict[str, Any] = Field(default_factory=dict)
    prompt_cache_key: str | None = None


class AnyAgentDoneEvent(StageEventBase):
    """Terminal stage event emitted when `[DONE]` is observed."""

    type: Literal["anyagent.done"] = "anyagent.done"


class AnyAgentPromptContextEvent(StageEventBase, PromptContextAudit):
    """Prompt assembly summary emitted before model invocation."""

    type: Literal["anyagent.prompt.context"] = "anyagent.prompt.context"


class AnyAgentPromptContextRenderedEvent(StageEventBase):
    """Fully rendered prompt fragments emitted for historical replay."""

    type: Literal["anyagent.prompt.context.rendered"] = "anyagent.prompt.context.rendered"
    prompt_cache_key: str | None = None
    fragments: list[RenderedPromptFragment] = Field(default_factory=list)
    total_chars: int = Field(default=0, ge=0)


class AnyAgentWorkspaceLifecycleEvent(StageEventBase):
    """Workspace lifecycle event for sandbox session filesystem."""

    type: Literal[
        "anyagent.sandbox.workspace.restoring",
        "anyagent.sandbox.workspace.restored",
        "anyagent.sandbox.workspace.checkpointing",
        "anyagent.sandbox.workspace.checkpointed",
        "anyagent.sandbox.workspace.hibernated",
        "anyagent.sandbox.workspace.restore_failed",
        "anyagent.sandbox.workspace.checkpoint_failed",
    ]
    session_partition_key: str
    workspace_id: str
    generation: int | None = Field(default=None, ge=0)
    sandbox_id: str | None = None
    snapshot_uri: str | None = None
    snapshot_bytes: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    audit_ref: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    runtime_diagnostics: AdminSandboxRuntimeDiagnostics | None = None


StageEvent: TypeAlias = Annotated[
    AnyAgentModelStreamEvent
    | AnyAgentToolPlannedEvent
    | AnyAgentToolResultEvent
    | AnyAgentToolExecutionDetailEvent
    | AnyAgentCommandPlannedEvent
    | AnyAgentCommandResultEvent
    | AnyAgentPromptContextEvent
    | AnyAgentPromptContextRenderedEvent
    | AnyAgentModelRequestEvent
    | AnyAgentWorkspaceLifecycleEvent
    | AnyAgentDoneEvent,
    Field(discriminator="type"),
]

_STAGE_EVENT_ADAPTER = TypeAdapter(StageEvent)


def parse_stage_event_seq(raw_seq: str | int | None) -> int | None:
    """Parse a best-effort event sequence value from SSE `id` or persisted rows."""

    if isinstance(raw_seq, int):
        return raw_seq if raw_seq >= 1 else None
    if not isinstance(raw_seq, str):
        return None
    text = raw_seq.strip()
    if not text.isdigit():
        return None
    try:
        seq = int(text)
    except Exception:  # noqa: BLE001
        return None
    return seq if seq >= 1 else None


def decode_stage_event(
    *,
    response_id: str,
    event: str | None,
    data: str,
    seq: int | None = None,
    include_model_events: bool = True,
    default_ts_ms: int | None = None,
) -> StageEvent | None:
    """Decode one persisted internal event row or SSE block into the typed union."""

    ts_ms = default_ts_ms if default_ts_ms is not None else int(time.time() * 1000)

    if event is None and isinstance(data, str) and data.strip() == "[DONE]":
        return AnyAgentDoneEvent(response_id=response_id, seq=seq, ts_ms=ts_ms)

    if isinstance(event, str) and event.startswith("anyagent.") and isinstance(data, str):
        try:
            payload = json.loads(data)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(payload, dict):
            return None
        payload.setdefault("type", event)
        payload.setdefault("response_id", response_id)
        payload.setdefault("seq", seq)
        if "ts_ms" not in payload:
            payload["ts_ms"] = ts_ms
        try:
            return _STAGE_EVENT_ADAPTER.validate_python(payload)
        except Exception:  # noqa: BLE001
            return None

    if not include_model_events:
        return None

    if not isinstance(event, str):
        return None
    if not (event.startswith("response.") or event == "error"):
        return None
    if not isinstance(data, str) or not data.strip():
        return None
    try:
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return AnyAgentModelStreamEvent(
        response_id=response_id,
        seq=seq,
        sse_event=event,
        payload=payload,
        ts_ms=ts_ms,
    )
