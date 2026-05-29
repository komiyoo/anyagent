from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from anyagent.agent_packs import load_agent_catalog
from anyagent.mcp.auth import CredentialResolver
from anyagent.protocol.tool_runtime import AuthRef, ExecuteRequest, ManifestRequest, PolicyHint, ToolContext
from anyagent.server.runtime import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager
from anyagent.tool_runtime import ToolRuntimeClient, create_tool_runtime_app
from anyagent.tool_runtime.models import ToolCredentialSpec, ToolDefinition


class _MemoryCredentialResolver(CredentialResolver):
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = dict(values)
        self.seen: list[tuple[str | None, str | None, dict[str, Any] | None]] = []

    async def resolve(self, auth_ref: AuthRef, *, scope_context: dict[str, Any] | None = None) -> str | None:
        self.seen.append((auth_ref.kind, auth_ref.ref, dict(scope_context or {})))
        return self.values.get((auth_ref.kind or "", auth_ref.ref or ""))


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - app.*",
                "  policy:",
                "    allow_tools:",
                "      - app.*",
                "    deny_tools:",
                "      - app.blocked",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _definition(
    name: str,
    *,
    credentials: list[ToolCredentialSpec] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} contract fixture",
        category="app",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": ["message"],
            "properties": {"message": {"type": "string"}},
        },
        credentials=credentials or [],
    )


async def _echo_handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    return json.dumps(
        {
            "message": args["message"],
            "agent_id": context["agent_id"],
            "session_key": context["session_key"],
        },
        sort_keys=True,
    )


async def _secret_handler(args: dict[str, Any], context: dict[str, Any]) -> str:
    _ = args
    return json.dumps({"secret": context["_credentials"]["secret:api_key"]}, sort_keys=True)


def _build_inprocess_runtime(tmp_path: Path) -> tuple[InProcessToolRuntimeService, _MemoryCredentialResolver]:
    _write_workspace(tmp_path)
    credentials = _MemoryCredentialResolver({("api_key", "search"): "sk-contract"})
    runtime = InProcessToolRuntimeService(
        workspace_dir=str(tmp_path),
        catalog=load_agent_catalog(workspace_dir=tmp_path),
        sandbox_manager=SandboxManager(root_dir=tmp_path / ".sandbox"),
        credential_store=credentials,
    )
    _register_contract_tools(runtime.register_tool)
    return runtime, credentials


def _register_contract_tools(register_tool: Any) -> None:
    register_tool(_definition("app.echo"), _echo_handler)
    register_tool(
        _definition(
            "app.secret",
            credentials=[
                ToolCredentialSpec(
                    ref_kind="api_key",
                    injection_target="secret:api_key",
                    format="Bearer {value}",
                )
            ],
        ),
        _secret_handler,
    )
    register_tool(_definition("app.blocked"), _echo_handler)


def test_inprocess_tool_runtime_contract_matrix_covers_manifest_execute_credentials_policy(tmp_path: Path) -> None:
    asyncio.run(_run_inprocess_tool_runtime_contract_matrix_covers_manifest_execute_credentials_policy(tmp_path))


async def _run_inprocess_tool_runtime_contract_matrix_covers_manifest_execute_credentials_policy(tmp_path: Path) -> None:
    runtime, credentials = _build_inprocess_runtime(tmp_path)
    result = await _exercise_contract_matrix(runtime)

    assert result == {
        "blocked_error": "tool_not_allowed",
        "echo": {
            "agent_id": "main",
            "message": "hello",
            "session_key": "sess-contract",
        },
        "manifest_tools": ["app.echo", "app.secret"],
        "missing_secret_error": "credential_not_found",
        "secret": {"secret": "Bearer sk-contract"},
    }
    assert credentials.seen == [
        ("api_key", "search", {"agent_id": "main"}),
        ("api_key", "missing", {"agent_id": "main"}),
    ]


def test_standalone_tool_runtime_matches_inprocess_contract_matrix(tmp_path: Path) -> None:
    asyncio.run(_run_standalone_tool_runtime_matches_inprocess_contract_matrix(tmp_path))


async def _run_standalone_tool_runtime_matches_inprocess_contract_matrix(tmp_path: Path) -> None:
    inprocess_runtime, _inprocess_credentials = _build_inprocess_runtime(tmp_path / "inprocess")
    inprocess_result = await _exercise_contract_matrix(inprocess_runtime)

    workspace = tmp_path / "standalone"
    _write_workspace(workspace)
    standalone_credentials = _MemoryCredentialResolver({("api_key", "search"): "sk-contract"})
    app = create_tool_runtime_app(
        workspace_dir=workspace,
        internal_key="internal-key",
        credential_store=standalone_credentials,
        sandbox_root_dir=workspace / ".sandbox",
    )
    _register_contract_tools(app.state.anyagent_tool_runtime.register_tool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = ToolRuntimeClient(base_url="http://testserver", internal_key="internal-key", http=http)
        standalone_result = await _exercise_contract_matrix(client)

    assert standalone_result == inprocess_result
    assert standalone_credentials.seen == [
        ("api_key", "search", {"agent_id": "main"}),
        ("api_key", "missing", {"agent_id": "main"}),
    ]


async def _exercise_contract_matrix(runtime: Any) -> dict[str, Any]:
    manifest = await runtime.manifest(
        ManifestRequest(
            agent_id="main",
            session_key="sess-contract",
            requested_tool_names=["app.echo", "app.secret", "app.blocked"],
            context=ToolContext(),
        )
    )
    assert [tool.name for tool in manifest.tools] == ["app.echo", "app.secret"]
    assert manifest.toolset_version >= 1

    executed = await runtime.execute(
        ExecuteRequest(
            agent_id="main",
            session_key="sess-contract",
            response_id="resp-contract",
            tool_call_id="call-echo",
            tool_name="app.echo",
            arguments_json={"message": "hello"},
            toolset_version=manifest.toolset_version,
            context=ToolContext(),
        )
    )
    assert executed.status == "completed"
    echo_output = json.loads(executed.output)

    secret = await runtime.execute(
        ExecuteRequest(
            agent_id="main",
            session_key="sess-contract",
            response_id="resp-contract",
            tool_call_id="call-secret",
            tool_name="app.secret",
            arguments_json={"message": "secret"},
            toolset_version=manifest.toolset_version,
            context=ToolContext(auth_ref=AuthRef(kind="api_key", ref="search")),
        )
    )
    assert secret.status == "completed"
    secret_output = json.loads(secret.output)

    missing_secret = await runtime.execute(
        ExecuteRequest(
            agent_id="main",
            session_key="sess-contract",
            response_id="resp-contract",
            tool_call_id="call-missing-secret",
            tool_name="app.secret",
            arguments_json={"message": "secret"},
            toolset_version=manifest.toolset_version,
            context=ToolContext(auth_ref=AuthRef(kind="api_key", ref="missing")),
        )
    )
    assert missing_secret.status == "error"

    blocked = await runtime.execute(
        ExecuteRequest(
            agent_id="main",
            session_key="sess-contract",
            response_id="resp-contract",
            tool_call_id="call-blocked",
            tool_name="app.blocked",
            arguments_json={"message": "blocked"},
            toolset_version=manifest.toolset_version,
            context=ToolContext(policy=PolicyHint(allow_tools=["app.*"])),
        )
    )
    assert blocked.status == "error"
    return {
        "blocked_error": blocked.error.code,
        "echo": echo_output,
        "manifest_tools": [tool.name for tool in manifest.tools],
        "missing_secret_error": missing_secret.error.code,
        "secret": secret_output,
    }
