from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from anyagent.protocol.sandbox import ResourceLimits, SandboxPolicy
from anyagent.server.sandbox import SandboxManager
from anyagent.server.sandbox.backends import CommandExecutionResult, CommandStagedFile
from anyagent.tool_runtime.cli_profile import build_cli_profile_handler, build_cli_profile_tool
from anyagent.tool_runtime.cli_profile_spec import CliEnvironmentPolicy, CliProfileSpec
from anyagent.tool_runtime.models import ToolCredentialSpec


def test_build_cli_profile_tool_exposes_internal_manifest_summary() -> None:
    profile = CliProfileSpec(
        name="app.demo",
        description="Demo CLI",
        cwd="repo",
        allow_command_prefixes=["npm run "],
        env=CliEnvironmentPolicy(set={"MODE": "demo"}),
        credentials=[
            ToolCredentialSpec(
                ref_kind="bearer_token",
                injection_target="env:API_TOKEN",
                credential_id="cred_demo",
            )
        ],
    )

    tool = build_cli_profile_tool(profile)

    assert tool.kind == "command"
    assert tool.manifest_extensions["x-anyagent-cli"] == {
        "cwd": "repo",
        "timeout_ms": 60000,
        "env": {
            "inherit": "core",
            "ignore_default_excludes": False,
            "exclude": [],
            "include_only": [],
            "set": {"MODE": "demo"},
        },
        "allow_command_prefixes": ["npm run "],
        "credential_targets": ["env:API_TOKEN"],
    }


def test_cli_profile_handler_injects_env_and_file_credentials(tmp_path: Path) -> None:
    async def _run() -> None:
        manager = SandboxManager(root_dir=tmp_path / ".sandbox")
        profile = CliProfileSpec(
            name="app.demo",
            cwd="repo",
            env=CliEnvironmentPolicy(inherit="none", set={"BASE": "yes"}),
            credentials=[
                ToolCredentialSpec(ref_kind="api_key", injection_target="env:API_TOKEN"),
                ToolCredentialSpec(ref_kind="api_key", injection_target="file:secrets/token.txt"),
            ],
        )
        handler = build_cli_profile_handler(
            profile=profile,
            sandbox_manager=manager,
            sandbox_policy_for_agent=lambda _agent_id: SandboxPolicy(mode="local-unsafe"),
        )

        output = await handler(
            {"cmd": "printf '%s|%s|%s' \"$BASE\" \"$API_TOKEN\" \"$(cat secrets/token.txt)\""},
            {
                "agent_id": "main",
                "session_key": "sess-cli",
                "_credentials": {
                    "env:API_TOKEN": "token-value",
                    "file:secrets/token.txt": "file-secret",
                },
            },
        )
        payload = json.loads(output)

        assert payload["exit_code"] == 0
        assert payload["stdout"] == "yes|token-value|file-secret"
        assert payload["profile"] == "app.demo"
        assert not (Path(payload["workdir"]) / "secrets" / "token.txt").exists()

    asyncio.run(_run())


def test_cli_profile_handler_enforces_prefix_and_banned_shell() -> None:
    profile = CliProfileSpec(name="app.demo", allow_command_prefixes=["npm run "])
    handler = build_cli_profile_handler(
        profile=profile,
        sandbox_manager=object(),
        sandbox_policy_for_agent=lambda _agent_id: SandboxPolicy(mode="local-unsafe"),
    )

    with pytest.raises(ValueError, match="allowed prefixes"):
        asyncio.run(handler({"cmd": "git status"}, {"agent_id": "main", "session_key": "sess"}))

    with pytest.raises(ValueError, match="banned shell token"):
        asyncio.run(handler({"cmd": "bash -lc 'echo nope'"}, {"agent_id": "main", "session_key": "sess"}))


def test_cli_profile_handler_reports_timeout_and_truncation(tmp_path: Path) -> None:
    async def _run() -> None:
        manager = SandboxManager(root_dir=tmp_path / ".sandbox")
        profile = CliProfileSpec(name="app.demo", cwd="repo", timeout_ms=1000, env=CliEnvironmentPolicy(inherit="none"))

        def _policy(_agent_id: str) -> SandboxPolicy:
            return SandboxPolicy(mode="local-unsafe", resource_limits=ResourceLimits(output_max_bytes=5))

        handler = build_cli_profile_handler(
            profile=profile,
            sandbox_manager=manager,
            sandbox_policy_for_agent=_policy,
        )

        truncated = json.loads(
            await handler(
                {"cmd": "printf '123456789'; printf 'ABCDE' >&2"},
                {"agent_id": "main", "session_key": "sess-truncate"},
            )
        )
        assert truncated["output_truncated"] is True
        assert truncated["stdout"] == "12345"
        assert truncated["stderr"] == ""

        timed_out = json.loads(
            await handler(
                {"cmd": "sleep 2"},
                {"agent_id": "main", "session_key": "sess-timeout"},
            )
        )
        assert timed_out["timed_out"] is True
        assert timed_out["exit_code"] == 124

        non_zero = json.loads(
            await handler(
                {"cmd": "false"},
                {"agent_id": "main", "session_key": "sess-fail"},
            )
        )
        assert non_zero["timed_out"] is False
        assert non_zero["exit_code"] == 1

    asyncio.run(_run())


def test_cli_profile_handler_supports_opensandbox_env_and_file_injection() -> None:
    class _Manager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def execute(self, **kwargs):
            self.calls.append(dict(kwargs))
            return CommandExecutionResult(
                command=str(kwargs["cmd"]),
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=1,
                cwd=str(kwargs["workdir"]),
            )

    async def _run() -> None:
        manager = _Manager()
        profile = CliProfileSpec(
            name="app.demo",
            cwd="repo",
            env=CliEnvironmentPolicy(inherit="none"),
            credentials=[
                ToolCredentialSpec(ref_kind="api_key", injection_target="env:API_TOKEN"),
                ToolCredentialSpec(ref_kind="api_key", injection_target="file:secrets/token.txt"),
            ],
        )
        handler = build_cli_profile_handler(
            profile=profile,
            sandbox_manager=manager,
            sandbox_policy_for_agent=lambda _agent_id: SandboxPolicy(mode="opensandbox"),
        )
        payload = json.loads(
            await handler(
                {"cmd": "printf ok"},
                {
                    "agent_id": "main",
                    "session_key": "sess-open",
                    "_credentials": {
                        "env:API_TOKEN": "token-value",
                        "file:secrets/token.txt": "file-secret",
                    },
                },
            )
        )

        assert payload["exit_code"] == 0
        call = manager.calls[0]
        assert call["env"] == {"API_TOKEN": "token-value"}
        assert call["staged_files"] == [
            CommandStagedFile(relative_path="secrets/token.txt", content="file-secret")
        ]

    asyncio.run(_run())
