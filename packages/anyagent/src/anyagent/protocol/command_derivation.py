from __future__ import annotations

"""
Command stage event derivation helpers (SSOT).

This module centralizes the best-effort rules to derive `anyagent.command.*`
stage events from tool calls/results, so server/client do not drift.
"""

import json
import shlex
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .tool_manifest_extensions import AnyAgentToolKind


class CommandPlannedFields(BaseModel):
    """Extracted command planned fields derived from tool arguments."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    workdir: str | None = None
    timeout_ms: int | None = Field(default=None, ge=0)


class CommandResultFields(BaseModel):
    """Extracted command result fields derived from tool output."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int | None = None
    stdout: Any | None = None
    stderr: Any | None = None


def is_command_like_tool_name(tool_name: str) -> bool:
    """Return True if a tool name is likely to represent a command execution."""

    if not isinstance(tool_name, str) or not tool_name.strip():
        return False
    name = tool_name.strip().lower()

    # Keep this conservative and stable: prefer obvious names, avoid broad matches.
    if name in {"core.shell", "core.command"}:
        return True
    if name.endswith(".shell") or name.endswith(".command") or name.endswith(".exec") or name.endswith(".run"):
        return True
    if ".shell_" in name or ".command_" in name:
        return True
    return False


def is_command_like_tool(*, tool_name: str, tool_kind: AnyAgentToolKind | None) -> bool:
    """
    Determine whether a tool call should be treated as a command stage.

    Rules:
    - If `tool_kind` is explicitly provided, it is authoritative.
    - Otherwise fall back to name-based heuristics for backward compatibility.
    """

    if tool_kind is not None:
        return tool_kind == "command"
    return is_command_like_tool_name(tool_name)


def extract_command_planned_fields(
    *, tool_name: str, tool_kind: AnyAgentToolKind | None, arguments_json: Any
) -> CommandPlannedFields | None:
    """Derive command/workdir/timeout from a command-like tool arguments object (best-effort)."""

    if not is_command_like_tool(tool_name=tool_name, tool_kind=tool_kind):
        return None
    if not isinstance(arguments_json, dict):
        return None

    cmd: str | None = None
    for k in ("command", "cmd", "bash", "script"):
        v = arguments_json.get(k)
        if isinstance(v, str) and v.strip():
            cmd = v.strip()
            break

    if cmd is None:
        argv = arguments_json.get("argv") or arguments_json.get("args")
        if isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv):
            cmd = " ".join(shlex.quote(x) for x in argv if x)

    if cmd is None:
        return None

    workdir = arguments_json.get("workdir") or arguments_json.get("cwd")
    workdir_out = workdir.strip() if isinstance(workdir, str) and workdir.strip() else None

    timeout_ms = arguments_json.get("timeout_ms")
    timeout_is_seconds = False
    if timeout_ms is None:
        timeout_ms = arguments_json.get("timeout")
        timeout_is_seconds = timeout_ms is not None
    timeout_out: int | None = None
    if isinstance(timeout_ms, int):
        timeout_out = max(0, int(timeout_ms) * (1000 if timeout_is_seconds else 1))

    return CommandPlannedFields(command=cmd, workdir=workdir_out, timeout_ms=timeout_out)


def extract_command_result_fields(
    *, tool_name: str, tool_kind: AnyAgentToolKind | None, tool_output: Any, max_parse_chars: int = 200_000
) -> CommandResultFields | None:
    """Derive exit_code/stdout/stderr from a command-like tool output string (best-effort)."""

    if not is_command_like_tool(tool_name=tool_name, tool_kind=tool_kind):
        return None
    if not isinstance(tool_output, str) or not tool_output.strip():
        return None

    out = tool_output.strip()
    if not out.startswith("{"):
        return None
    if len(out) > int(max_parse_chars):
        return None

    try:
        obj = json.loads(out)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(obj, dict):
        return None

    exit_code: int | None = None
    ec = obj.get("exit_code")
    if ec is None:
        ec = obj.get("code")
    if ec is None:
        ec = obj.get("returncode")
    if isinstance(ec, int):
        exit_code = int(ec)

    return CommandResultFields(exit_code=exit_code, stdout=obj.get("stdout"), stderr=obj.get("stderr"))
