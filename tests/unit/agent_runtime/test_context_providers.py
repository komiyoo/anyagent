from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from anyagent.agent_packs import AgentPack, AgentSpec
from anyagent.agent_runtime.context_providers import (
    BaseContextProvider,
    ContextProviderLoadError,
    ContextProviderRequest,
    collect_context_provider_fragments,
    load_context_provider_from_classpath,
)
from anyagent.protocol.context_fragments import ContextFragment
from anyagent.protocol.tool_runtime import ToolContext


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _request(tmp_path: Path) -> ContextProviderRequest:
    pack = AgentPack(
        agent_id="main",
        root_dir=tmp_path,
        spec=AgentSpec.model_validate({"exposed": True, "tools": {"requested_tool_names": []}}),
        agents_md_path=tmp_path / "AGENTS.md",
        agents_md_text="You are main.",
        agents_md_sha256="0" * 64,
    )
    return ContextProviderRequest(
        agent_id="main",
        session_key="sess-1",
        body={"input": "hello"},
        metadata={"context": {"channel": {"provider": "chatwoot"}}},
        workspace_dir=tmp_path,
        pack=pack,
        tool_context=ToolContext(),
        selected_skills=[],
    )


def test_loads_context_provider_from_classpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "custom_context_provider",
        """
        from anyagent.agent_runtime import BaseContextProvider

        class RouteContextProvider(BaseContextProvider):
            pass
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("custom_context_provider", None)

    provider = load_context_provider_from_classpath("custom_context_provider:RouteContextProvider")

    assert provider.__class__.__name__ == "RouteContextProvider"


def test_collect_context_provider_fragments_accepts_models_and_dicts(tmp_path: Path) -> None:
    class _Provider(BaseContextProvider):
        async def build_context(self, request: ContextProviderRequest) -> list[ContextFragment | dict[str, object]]:  # type: ignore[override]
            return [
                ContextFragment(
                    kind="business_context",
                    cache_class="contextual",
                    stable_id="business://one",
                    body=f"agent={request.agent_id}",
                ),
                {
                    "kind": "page_context",
                    "cache_class": "dynamic",
                    "stable_id": "page://two",
                    "body": "page facts",
                },
            ]

    fragments = asyncio.run(collect_context_provider_fragments([_Provider()], _request(tmp_path)))

    assert [fragment.kind for fragment in fragments] == ["business_context", "page_context"]
    assert fragments[0].body == "agent=main"
    assert fragments[1].body == "page facts"


@pytest.mark.parametrize("bad", ["NoColon", ":Missing", "mod:", "mod:1Class"])
def test_rejects_malformed_context_provider_classpath(bad: str) -> None:
    with pytest.raises(ContextProviderLoadError, match="invalid context provider classpath"):
        load_context_provider_from_classpath(bad)


def test_rejects_context_provider_missing_build_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "not_context_provider",
        """
        class NotAProvider:
            pass
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("not_context_provider", None)

    with pytest.raises(ContextProviderLoadError, match="does not implement build_context"):
        load_context_provider_from_classpath("not_context_provider:NotAProvider")
