from __future__ import annotations

import json
from typing import Any

from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.tool_runtime.models import ToolDefinition

from .manager import SandboxManager


EXEC_TOOL = ToolDefinition(
    name="exec",
    description="Execute a shell command in the sandbox environment.",
    parameters={
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "Shell command to execute."},
            "workdir": {"type": "string", "description": "Working directory relative to the sandbox root."},
            "timeout": {"type": "integer", "description": "Timeout in seconds."},
        },
        "required": ["cmd"],
        "additionalProperties": False,
    },
    category="core",
    kind="command",
)


def build_exec_handler(
    *,
    sandbox_manager: SandboxManager,
    sandbox_policy_for_agent: callable,
):
    async def _handler(arguments: dict[str, Any], context: dict[str, Any]) -> str:
        cmd = arguments.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("exec requires non-empty cmd")

        agent_id = context.get("agent_id")
        session_key = context.get("session_key")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("exec context missing agent_id")
        if not isinstance(session_key, str) or not session_key.strip():
            raise ValueError("exec context missing session_key")

        timeout = arguments.get("timeout")
        timeout_seconds = int(timeout) if isinstance(timeout, int) and timeout > 0 else 60
        workdir = arguments.get("workdir")
        workdir_value = workdir.strip() if isinstance(workdir, str) and workdir.strip() else None
        policy = sandbox_policy_for_agent(agent_id)
        if not isinstance(policy, SandboxPolicy):
            raise ValueError("sandbox policy is not configured")

        result = await sandbox_manager.execute(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            cmd=cmd.strip(),
            workdir=workdir_value,
            timeout_seconds=timeout_seconds,
            response_id=context.get("response_id") if isinstance(context.get("response_id"), str) else None,
            tool_call_id=context.get("tool_call_id") if isinstance(context.get("tool_call_id"), str) else None,
            trace_id=context.get("_trace_id") if isinstance(context.get("_trace_id"), str) else None,
            audit_ref=context.get("_audit_ref") if isinstance(context.get("_audit_ref"), str) else None,
        )
        output_max_bytes = None
        if policy.resource_limits is not None and isinstance(policy.resource_limits.output_max_bytes, int):
            output_max_bytes = max(policy.resource_limits.output_max_bytes, 0)
        stdout_value = result.stdout
        stderr_value = result.stderr
        output_truncated = False
        if output_max_bytes is not None:
            stdout_value, remaining_bytes, stdout_truncated = _truncate_text_utf8(stdout_value, output_max_bytes)
            stderr_value, _remaining_bytes, stderr_truncated = _truncate_text_utf8(stderr_value, remaining_bytes)
            output_truncated = stdout_truncated or stderr_truncated
        return json.dumps(
            {
                "command": result.command,
                "workdir": result.cwd,
                "exit_code": result.exit_code,
                "stdout": stdout_value,
                "stderr": stderr_value,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
                "output_truncated": output_truncated,
            },
            ensure_ascii=False,
        )

    return _handler


def _truncate_text_utf8(text: str, max_bytes: int) -> tuple[str, int, bool]:
    raw = text.encode("utf-8", errors="replace")
    budget = max(int(max_bytes), 0)
    if len(raw) <= budget:
        return text, budget - len(raw), False
    truncated = raw[:budget].decode("utf-8", errors="ignore")
    return truncated, 0, True
