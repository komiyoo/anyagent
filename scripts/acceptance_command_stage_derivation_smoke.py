from __future__ import annotations

"""
Acceptance smoke: command stage event derivation + type validation.

This test does NOT call upstream models.
It validates that:
- command-like tool derivation logic is centralized (SSOT) and stable
- StageEvent union accepts derived `anyagent.command.*` payloads
- command preview is suppressed when it looks sensitive
"""

import json

from pydantic import TypeAdapter

from anyagent.protocol.command_derivation import (
    extract_command_planned_fields,
    extract_command_result_fields,
    is_command_like_tool_name,
)
from anyagent.protocol.stage_events import (
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    StageEvent,
    summarize_command,
    summarize_payload,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def _smoke_planned() -> None:
    tool_name = "core.shell"
    _assert(is_command_like_tool_name(tool_name), "core.shell should be command-like")

    args = {"argv": ["echo", "hello"], "workdir": "/tmp", "timeout_ms": 1000}
    info = extract_command_planned_fields(tool_name=tool_name, tool_kind=None, arguments_json=args)
    _assert(info is not None, "planned fields should be derivable from argv/workdir/timeout_ms")
    _assert(info.command == "echo hello", "argv should be joined into a shell-safe command string")

    ev = AnyAgentCommandPlannedEvent(
        response_id="resp_test_1",
        command=summarize_command(info.command),
        workdir=info.workdir,
        timeout_ms=info.timeout_ms,
        source_tool_call_id="call_1",
        source_tool_name=tool_name,
        seq=7,
        ts_ms=1,
    )

    # Validate union parsing (what SDK does after json.loads).
    adapter = TypeAdapter(StageEvent)
    parsed = adapter.validate_python(ev.model_dump(exclude_none=True))
    _assert(parsed.type == "anyagent.command.planned", "StageEvent union should accept command.planned")


def _smoke_sensitive_preview() -> None:
    # Looks like a bearer token / secret; preview should be suppressed by default.
    cmd = "curl -H 'Authorization: Bearer sk-THIS-IS-A-FAKE-KEY' https://example.com"
    summ = summarize_command(cmd)
    _assert(summ.preview is None, "sensitive-looking command should not include preview")


def _smoke_tool_kind_marker() -> None:
    # Marker should override name-based heuristics.
    tool_name = "app.not_shell"
    args = {"cmd": "echo hi"}
    info = extract_command_planned_fields(tool_name=tool_name, tool_kind="command", arguments_json=args)
    _assert(info is not None and info.command == "echo hi", "tool_kind=command should force command derivation")


def _smoke_result() -> None:
    tool_name = "core.shell"
    out = json.dumps({"exit_code": 0, "stdout": "ok", "stderr": ""})
    info = extract_command_result_fields(tool_name=tool_name, tool_kind=None, tool_output=out)
    _assert(info is not None and info.exit_code == 0, "result fields should be derivable from JSON output")

    ev = AnyAgentCommandResultEvent(
        response_id="resp_test_1",
        exit_code=info.exit_code,
        stdout=summarize_payload(info.stdout),
        stderr=summarize_payload(info.stderr),
        duration_ms=12,
        source_tool_call_id="call_1",
        source_tool_name=tool_name,
        seq=8,
        ts_ms=2,
    )

    adapter = TypeAdapter(StageEvent)
    parsed = adapter.validate_python(ev.model_dump(exclude_none=True))
    _assert(parsed.type == "anyagent.command.result", "StageEvent union should accept command.result")


def main() -> int:
    """Run command stage derivation acceptance smoke."""
    _smoke_planned()
    _smoke_sensitive_preview()
    _smoke_tool_kind_marker()
    _smoke_result()
    print("ok: acceptance_command_stage_derivation_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
