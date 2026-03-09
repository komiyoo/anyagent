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
        )
        return json.dumps(
            {
                "command": result.command,
                "workdir": result.cwd,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
            },
            ensure_ascii=False,
        )

    return _handler
