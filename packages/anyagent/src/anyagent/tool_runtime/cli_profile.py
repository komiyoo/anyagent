from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.server.sandbox.backends import CommandStagedFile
from anyagent.tool_runtime.models import ToolDefinition

from anyagent.server.sandbox.exec_handler import _truncate_text_utf8

from .cli_env import build_cli_env
from .cli_profile_spec import BANNED_COMMAND_SHELLS, CliProfileSpec


def build_cli_profile_tool(profile: CliProfileSpec) -> ToolDefinition:
    credential_targets = [spec.injection_target for spec in profile.credentials]
    category = _category_for_profile_name(profile.name)
    return ToolDefinition(
        name=profile.name,
        description=profile.description,
        category=category,
        kind="command",
        parameters={
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Shell command to execute inside the CLI profile sandbox."},
                "workdir": {"type": "string", "description": "Working directory relative to the profile cwd."},
                "timeout": {"type": "integer", "description": "Timeout in seconds."},
            },
            "required": ["cmd"],
            "additionalProperties": False,
        },
        credentials=profile.credentials,
        manifest_extensions={
            "x-anyagent-cli": {
                "cwd": profile.cwd,
                "timeout_ms": profile.timeout_ms,
                "env": profile.env.model_dump(exclude_none=True),
                "allow_command_prefixes": list(profile.allow_command_prefixes),
                "credential_targets": credential_targets,
            }
        },
    )


def build_cli_profile_handler(
    *,
    profile: CliProfileSpec,
    sandbox_manager: Any,
    sandbox_policy_for_agent: Any,
):
    async def _handler(arguments: dict[str, Any], context: dict[str, Any]) -> str:
        cmd = arguments.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError(f"{profile.name} requires non-empty cmd")

        agent_id = context.get("agent_id")
        session_key = context.get("session_key")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("cli profile context missing agent_id")
        if not isinstance(session_key, str) or not session_key.strip():
            raise ValueError("cli profile context missing session_key")

        _validate_command(profile=profile, cmd=cmd)

        timeout_value = arguments.get("timeout")
        timeout_seconds = int(timeout_value) if isinstance(timeout_value, int) and timeout_value > 0 else max(
            1, profile.timeout_ms // 1000
        )
        workdir = arguments.get("workdir")
        workdir_value = _join_profile_workdir(profile.cwd, workdir if isinstance(workdir, str) else None)
        policy = sandbox_policy_for_agent(agent_id)
        if not isinstance(policy, SandboxPolicy):
            raise ValueError("sandbox policy is not configured")
        if profile.sandbox is not None:
            policy = SandboxPolicy.model_validate({**policy.model_dump(exclude_none=True), "mode": profile.sandbox})
        env = build_cli_env(profile.env)
        staged_files = _resolve_credential_injections(env=env, context=context)
        result = await sandbox_manager.execute(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            cmd=cmd.strip(),
            workdir=workdir_value,
            timeout_seconds=timeout_seconds,
            env=env,
            staged_files=staged_files,
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
                "profile": profile.name,
            },
            ensure_ascii=False,
        )

    return _handler


def _validate_command(*, profile: CliProfileSpec, cmd: str) -> None:
    parts = shlex.split(cmd, posix=True)
    if not parts:
        raise ValueError("cmd must not be empty")
    for part in parts[:2]:
        if part.lower() in BANNED_COMMAND_SHELLS:
            raise ValueError(f"cli profile {profile.name} command uses banned shell token: {part}")
    prefixes = [item.strip() for item in profile.allow_command_prefixes if item.strip()]
    if prefixes and not any(cmd.startswith(prefix) for prefix in prefixes):
        raise ValueError(f"cli profile {profile.name} command must start with one of the allowed prefixes")


def _join_profile_workdir(profile_cwd: str, workdir: str | None) -> str:
    base = PureProfilePath(profile_cwd)
    if workdir is None or not workdir.strip():
        return base.value
    return base.join(workdir).value


class PureProfilePath:
    def __init__(self, value: str) -> None:
        cleaned = value.strip() or "."
        normalized_parts: list[str] = []
        for part in Path(cleaned).parts:
            if part in {"", "."}:
                continue
            if part == ".." or os.path.isabs(part):
                raise ValueError("cli profile cwd/workdir must stay within agent workspace")
            normalized_parts.append(part)
        self.value = "." if not normalized_parts else "/".join(normalized_parts)

    def join(self, extra: str) -> "PureProfilePath":
        if not extra.strip():
            return PureProfilePath(self.value)
        return PureProfilePath(f"{self.value}/{extra}" if self.value != "." else extra)


def _resolve_credential_injections(*, env: dict[str, str], context: dict[str, Any]) -> list[CommandStagedFile]:
    raw = context.get("_credentials")
    credential_values = raw if isinstance(raw, dict) else {}
    file_targets: list[CommandStagedFile] = []
    for target, value in credential_values.items():
        if not isinstance(target, str) or not isinstance(value, str):
            continue
        if target.startswith("env:"):
            env_name = target.removeprefix("env:").strip()
            if env_name:
                env[env_name] = value
        elif target.startswith("file:"):
            relative = target.removeprefix("file:").strip()
            if not relative:
                continue
            file_targets.append(CommandStagedFile(relative_path=PureProfilePath(relative).value, content=value))
    return file_targets


def _category_for_profile_name(name: str) -> str:
    if name == "exec" or name.startswith("core.") or name.startswith("admin."):
        return "core"
    if name.startswith("app."):
        return "app"
    if name.startswith("sandbox."):
        return "sandbox"
    if "." in name:
        return "channel"
    return "core"
