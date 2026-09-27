from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from anyagent.agent_packs import AgentPack, AgentSpec
from anyagent.agent_runtime.scripted_reply import (
    BaseScriptedReplyProvider,
    ScriptedReplyLoadError,
    ScriptedReplyRequest,
    load_scripted_reply_provider_from_classpath,
    resolve_scripted_reply,
)
from anyagent.protocol.scripted_reply import ScriptedReply
from anyagent.protocol.stage_events import AnyAgentScriptedReplyEvent, decode_stage_event
from anyagent.protocol.tool_runtime import ToolContext


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _request(tmp_path: Path, *, previous: list[dict] | None = None) -> ScriptedReplyRequest:
    pack = AgentPack(
        agent_id="main",
        root_dir=tmp_path,
        spec=AgentSpec.model_validate({"exposed": True, "tools": {"requested_tool_names": []}}),
        agents_md_path=tmp_path / "AGENTS.md",
        agents_md_text="You are main.",
        agents_md_sha256="0" * 64,
    )
    return ScriptedReplyRequest(
        agent_id="main",
        session_key="sess-1",
        body={"input": "hello"},
        metadata={"context": {"channel": {"provider": "chatwoot"}}},
        workspace_dir=tmp_path,
        pack=pack,
        tool_context=ToolContext(),
        selected_skills=[],
        previous_transcript_items=list(previous or []),
    )


def test_scripted_reply_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        ScriptedReply(text="   ")
    with pytest.raises(ValidationError):
        ScriptedReply(text="ok", tool_calls=[])  # type: ignore[call-arg]


def test_scripted_reply_accepts_optional_delivery_attributes() -> None:
    plain = ScriptedReply(text="Hello")
    assert plain.model_dump(exclude_none=True) == {"text": "Hello"}
    structured = ScriptedReply(
        text="Choose one",
        content_type="input_select",
        content_attributes={"items": [{"title": "A", "value": "a"}]},
    )
    assert structured.content_attributes == {"items": [{"title": "A", "value": "a"}]}


def test_scripted_reply_stage_event_round_trips_through_decoder() -> None:
    event = AnyAgentScriptedReplyEvent(response_id="resp_1", provider="P", variant_id="v1", reason="greeting", text_chars=5)
    decoded = decode_stage_event(
        response_id="resp_1",
        event="anyagent.response.scripted",
        data=event.model_dump_json(exclude_none=True),
    )
    assert isinstance(decoded, AnyAgentScriptedReplyEvent)
    assert decoded.provider == "P"
    assert decoded.variant_id == "v1"


def test_request_exposes_first_turn(tmp_path: Path) -> None:
    assert _request(tmp_path).is_first_turn is True
    assert _request(tmp_path, previous=[{"role": "user", "content": "x"}]).is_first_turn is False


def test_loads_scripted_reply_provider_from_classpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "custom_scripted_reply",
        """
        from anyagent.agent_runtime import BaseScriptedReplyProvider

        class Greeter(BaseScriptedReplyProvider):
            pass
        """,
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("custom_scripted_reply", None)

    provider = load_scripted_reply_provider_from_classpath("custom_scripted_reply:Greeter")

    assert provider.__class__.__name__ == "Greeter"


@pytest.mark.parametrize("bad", ["NoColon", ":Missing", "mod:", "mod:1Class"])
def test_rejects_malformed_scripted_reply_classpath(bad: str) -> None:
    with pytest.raises(ScriptedReplyLoadError, match="invalid scripted reply provider classpath"):
        load_scripted_reply_provider_from_classpath(bad)


def test_rejects_provider_missing_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(tmp_path, "not_scripted_reply", "class NotAProvider:\n    pass\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("not_scripted_reply", None)

    with pytest.raises(ScriptedReplyLoadError, match="does not implement resolve"):
        load_scripted_reply_provider_from_classpath("not_scripted_reply:NotAProvider")


def test_resolve_returns_first_hit_in_order(tmp_path: Path) -> None:
    class _Miss(BaseScriptedReplyProvider):
        pass

    class _HitDict(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            return {"text": "dict hit", "variant_id": "d1"}

    class _HitModel(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            return ScriptedReply(text="model hit")

    match = asyncio.run(resolve_scripted_reply([_Miss(), _HitDict(), _HitModel()], _request(tmp_path)))

    assert match is not None
    assert match.provider_name == "_HitDict"
    assert match.reply.text == "dict hit"
    assert match.reply.variant_id == "d1"


def test_resolve_returns_none_when_all_providers_miss(tmp_path: Path) -> None:
    assert asyncio.run(resolve_scripted_reply([BaseScriptedReplyProvider()], _request(tmp_path))) is None
    assert asyncio.run(resolve_scripted_reply([], _request(tmp_path))) is None


def test_resolve_degrades_on_exception_timeout_and_malformed_return(tmp_path: Path) -> None:
    warnings: list[str] = []

    class _Raises(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            raise RuntimeError("boom")

    class _Slow(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            await asyncio.sleep(1.0)
            return {"text": "too late"}

    class _Malformed(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            return 42

    class _BlankText(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            return {"text": ""}

    class _Hit(BaseScriptedReplyProvider):
        async def resolve(self, request):  # type: ignore[override]
            return {"text": "finally"}

    match = asyncio.run(
        resolve_scripted_reply(
            [_Raises(), _Slow(), _Malformed(), _BlankText(), _Hit()],
            _request(tmp_path),
            timeout_s=0.05,
            warn=warnings.append,
        )
    )

    assert match is not None
    assert match.provider_name == "_Hit"
    assert len(warnings) == 4
    assert any("timed out" in w for w in warnings)
    assert any("_Raises" in w and "boom" in w for w in warnings)
