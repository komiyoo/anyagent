from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.config.agents import load_agent_catalog
from anyagent.protocol.tool_runtime import ExecuteMeta, ExecuteRequest, ToolContext
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager
from anyagent.tool_runtime.models import ToolCredentialSpec, ToolDefinition


class _FakeCredentialResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def resolve(self, auth_ref, *, scope_context):
        self.calls.append((auth_ref.kind, auth_ref.ref, dict(scope_context)))
        return "resolved-secret"


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "  cli:",
                "    - name: app.demo",
                "      cwd: repo",
                "      credentials:",
                "        - credential_id: cred_profile",
                "          ref_kind: bearer_token",
                "          injection_target: env:API_TOKEN",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_in_process_credential_resolution_prefers_cli_profile_credential_id(tmp_path: Path) -> None:
    async def _run() -> None:
        _write_workspace(tmp_path)
        resolver = _FakeCredentialResolver()
        service = InProcessToolRuntimeService(
            workspace_dir=str(tmp_path),
            catalog=load_agent_catalog(workspace_dir=tmp_path),
            sandbox_manager=SandboxManager(root_dir=tmp_path / ".sandbox"),
            credential_store=resolver,
        )
        req = ExecuteRequest(
            agent_id="main",
            session_key="sess-1",
            response_id="resp-1",
            tool_call_id="call-1",
            tool_name="app.demo",
            arguments_json={},
            toolset_version=1,
            context=ToolContext.model_validate(
                {"auth_ref": {"kind": "bearer_token", "ref": "cred_request_override"}}
            ),
        )
        registered = type(
            "_Registered",
            (),
            {
                "definition": ToolDefinition(
                    name="app.demo",
                    category="core",
                    parameters={},
                    credentials=[
                        ToolCredentialSpec(
                            credential_id="cred_profile",
                            ref_kind="bearer_token",
                            injection_target="env:API_TOKEN",
                        )
                    ],
                )
            },
        )()

        resolved = await service._resolve_tool_credentials(  # noqa: SLF001
            req=req,
            audit_ref="aud-test",
            registered=registered,
            meta_factory=lambda: ExecuteMeta(audit_ref="aud-test"),
        )

        assert resolved == {"env:API_TOKEN": "resolved-secret"}
        assert resolver.calls == [("bearer_token", "cred_profile", {"agent_id": "main"})]

    asyncio.run(_run())
