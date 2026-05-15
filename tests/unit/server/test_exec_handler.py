from __future__ import annotations

import asyncio
import json

from anyagent.protocol.sandbox import ResourceLimits, SandboxPolicy
from anyagent.server.sandbox.backends import CommandExecutionResult
from anyagent.server.sandbox.exec_handler import _truncate_text_utf8, build_exec_handler


class _FakeSandboxManager:
    def __init__(self, result: CommandExecutionResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return self._result


def test_truncate_text_utf8_preserves_valid_boundary() -> None:
    value, remaining, truncated = _truncate_text_utf8("你好ab", 5)

    assert value == "你"
    assert remaining == 0
    assert truncated is True


def test_exec_handler_applies_output_budget_across_stdout_and_stderr() -> None:
    async def _run() -> None:
        manager = _FakeSandboxManager(
            CommandExecutionResult(
                command="printf test",
                exit_code=0,
                stdout="abcd",
                stderr="efg",
                duration_ms=12,
                cwd="/tmp/session",
                timed_out=False,
            )
        )
        handler = build_exec_handler(
            sandbox_manager=manager,
            sandbox_policy_for_agent=lambda _agent_id: SandboxPolicy(
                mode="local-unsafe",
                resource_limits=ResourceLimits(output_max_bytes=5),
            ),
        )

        raw = await handler(
            {"cmd": "  printf test  ", "workdir": " nested ", "timeout": 7},
            {"agent_id": "main", "session_key": "sess-1"},
        )
        payload = json.loads(raw)

        assert manager.calls == [
            {
                "policy": SandboxPolicy(mode="local-unsafe", resource_limits=ResourceLimits(output_max_bytes=5)),
                "agent_id": "main",
                "session_key": "sess-1",
                "cmd": "printf test",
                "workdir": "nested",
                "timeout_seconds": 7,
                "response_id": None,
                "tool_call_id": None,
                "trace_id": None,
                "audit_ref": None,
            }
        ]
        assert payload["stdout"] == "abcd"
        assert payload["stderr"] == "e"
        assert payload["output_truncated"] is True

    asyncio.run(_run())
