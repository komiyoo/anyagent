from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path
from typing import Any

from anyagent.agent_packs import AgentPack, AgentSpec
from anyagent.mcp import MCPManagerRegistry
from anyagent.server.persistence.manifest_cache import ManifestCache
from anyagent.server.responses.response_tooling import ResponseToolingContextError, prepare_response_tooling_context


def _pack(*, root_dir: Path = Path("/tmp/main"), runtime: dict[str, Any] | None = None) -> AgentPack:
    return AgentPack(
        agent_id="main",
        root_dir=root_dir,
        spec=AgentSpec.model_validate(
            {
                "exposed": True,
                "tools": {
                    "requested_tool_names": ["agent.tool"],
                    "policy": {"allow_tools": ["core.echo"], "deny_tools": ["bad.tool"]},
                },
                "skills": {"default_selected": [], "disabled_paths": []},
                "sandbox": {"mode": "local-unsafe"},
                "runtime": runtime or {},
            }
        ),
        agents_md_path=root_dir / "AGENTS.md",
        agents_md_text="You are a test agent.",
        agents_md_sha256="0" * 64,
    )


class _MultiAgent:
    def system_tools_for_pack(self, _pack: AgentPack) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "spawn_agent",
                "description": "Spawn an agent",
                "parameters": {"type": "object", "properties": {}},
            }
        ]


def test_prepare_response_tooling_context_builds_manifest_prompt_and_cache() -> None:
    asyncio.run(_run_prepare_response_tooling_context_builds_manifest_prompt_and_cache())


async def _run_prepare_response_tooling_context_builds_manifest_prompt_and_cache() -> None:
    calls: list[dict[str, Any]] = []

    async def _fetch_manifest_tools(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        calls.append(kwargs)
        return (
            [
                {
                    "type": "function",
                    "name": "core.echo",
                    "description": "Echo",
                    "parameters": {"type": "object", "properties": {}},
                    "x-anyagent-kind": "internal",
                }
            ],
            7,
        )

    cache = ManifestCache(ttl_seconds=60)
    requested_tools = [
        {
            "type": "function",
            "name": "request.tool",
            "description": "Requested",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    body = {
        "model": "gpt-test",
        "input": "hello",
        "tool_choice": {"type": "function", "name": "core.echo"},
        "tools": requested_tools,
    }
    metadata = {
        "context": {
            "policy": {"allow_tools": ["caller.injected"]},
            "trace": {"trace_id": "trace_1"},
        }
    }

    first = await prepare_response_tooling_context(
        body=body,
        metadata=metadata,
        pack=_pack(),
        agent_id="main",
        session_key="sess-1",
        workspace_dir=Path("/tmp/workspace"),
        agent_skills={},
        global_skills=[],
        manifest_cache=cache,
        tool_runtime=object(),  # type: ignore[arg-type]
        mcp_registry=MCPManagerRegistry(),
        mcp_credential_store=None,
        multiagent=_MultiAgent(),
        fetch_manifest_tools_fn=_fetch_manifest_tools,
    )
    second = await prepare_response_tooling_context(
        body={
            "model": "gpt-test",
            "input": "hello again",
            "tool_choice": {"type": "function", "name": "core.echo"},
            "tools": requested_tools,
        },
        metadata=metadata,
        pack=_pack(),
        agent_id="main",
        session_key="sess-1",
        workspace_dir=Path("/tmp/workspace"),
        agent_skills={},
        global_skills=[],
        manifest_cache=cache,
        tool_runtime=object(),  # type: ignore[arg-type]
        mcp_registry=MCPManagerRegistry(),
        mcp_credential_store=None,
        multiagent=_MultiAgent(),
        fetch_manifest_tools_fn=_fetch_manifest_tools,
    )

    assert len(calls) == 1
    assert calls[0]["requested_tool_names"] == ["agent.tool", "request.tool"]
    assert calls[0]["context"]["policy"] == {"allow_tools": ["core.echo"], "deny_tools": ["bad.tool"]}
    assert calls[0]["context"]["trace"] == {"trace_id": "trace_1"}
    assert first.toolset_version == 7
    assert second.toolset_version == 7
    assert [tool["name"] for tool in first.manifest_tools] == ["core.echo", "spawn_agent"]
    assert first.body["tools"][0]["name"] == "core_echo"
    assert "x-anyagent-kind" not in first.body["tools"][0]
    assert first.body["tools"][1]["name"] == "spawn_agent"
    assert first.prompt_audit is not None


def test_prepare_response_tooling_context_injects_context_provider_fragments(tmp_path: Path) -> None:
    asyncio.run(_run_prepare_response_tooling_context_injects_context_provider_fragments(tmp_path))


async def _run_prepare_response_tooling_context_injects_context_provider_fragments(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "route_context_provider.py").write_text(
        textwrap.dedent(
            """
            from anyagent.agent_runtime import BaseContextProvider
            from anyagent.protocol.context_fragments import ContextFragment

            class RouteContextProvider(BaseContextProvider):
                async def build_context(self, request):
                    page_url = (
                        request.metadata
                        .get("context", {})
                        .get("channel", {})
                        .get("ext", {})
                        .get("chatwoot_page_context", {})
                        .get("entry_url")
                    )
                    return [
                        ContextFragment(
                            kind="page_context",
                            cache_class="dynamic",
                            stable_id="page://route",
                            source_path=page_url,
                            body="<route_context>Golden Triangle route facts.</route_context>",
                        )
                    ]
            """
        ),
        encoding="utf-8",
    )
    sys.modules.pop("route_context_provider", None)

    async def _fetch_manifest_tools(**_kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        return ([], 1)

    metadata = {
        "context": {
            "channel": {
                "provider": "chatwoot",
                "ext": {
                    "chatwoot_page_context": {
                        "entry_url": "https://www.lyriktrip.com/tours/best-of-china-golden-triangle"
                    }
                },
            }
        }
    }

    result = await prepare_response_tooling_context(
        body={"input": "hello"},
        metadata=metadata,
        pack=_pack(root_dir=tmp_path / "main", runtime={"context_providers": ["route_context_provider:RouteContextProvider"]}),
        agent_id="main",
        session_key="sess-1",
        workspace_dir=tmp_path,
        agent_skills={},
        global_skills=[],
        manifest_cache=ManifestCache(ttl_seconds=60),
        tool_runtime=object(),  # type: ignore[arg-type]
        mcp_registry=MCPManagerRegistry(),
        mcp_credential_store=None,
        multiagent=_MultiAgent(),
        fetch_manifest_tools_fn=_fetch_manifest_tools,
    )

    prompt_texts = [
        item.get("content")
        for item in result.body["input"]
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    ]
    assert any("Golden Triangle route facts." in text for text in prompt_texts)
    assert "page_context" not in result.prompt_audit.fragment_kinds
    assert not any(fragment.kind == "page_context" for fragment in result.prompt_envelope.fragments)


def test_prepare_response_tooling_context_rejects_invalid_tool_choice() -> None:
    asyncio.run(_run_prepare_response_tooling_context_rejects_invalid_tool_choice())


async def _run_prepare_response_tooling_context_rejects_invalid_tool_choice() -> None:
    async def _fetch_manifest_tools(**_kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        return (
            [
                {
                    "type": "function",
                    "name": "core.echo",
                    "description": "Echo",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            1,
        )

    try:
        await prepare_response_tooling_context(
            body={"tool_choice": {"type": "function", "name": "missing.tool"}},
            metadata=None,
            pack=_pack(),
            agent_id="main",
            session_key="sess-1",
            workspace_dir=Path("/tmp/workspace"),
            agent_skills={},
            global_skills=[],
            manifest_cache=ManifestCache(ttl_seconds=60),
            tool_runtime=object(),  # type: ignore[arg-type]
            mcp_registry=MCPManagerRegistry(),
            mcp_credential_store=None,
            multiagent=_MultiAgent(),
            fetch_manifest_tools_fn=_fetch_manifest_tools,
        )
    except ResponseToolingContextError as exc:
        assert exc.status_code == 400
        assert "tool_choice" in exc.message
    else:
        raise AssertionError("expected ResponseToolingContextError")
