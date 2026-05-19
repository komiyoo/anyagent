from __future__ import annotations

from pathlib import Path

from anyagent.agent_packs import AgentCatalog, AgentPack, AgentSpec
from anyagent.server.request_context import ResponsesRequestContextError, prepare_responses_request_context


def _pack(agent_id: str, *, exposed: bool = True, default_model: str | None = None) -> AgentPack:
    spec_data = {
        "exposed": exposed,
        "tools": {"requested_tool_names": []},
        "skills": {"default_selected": [], "disabled_paths": []},
    }
    if default_model is not None:
        spec_data["model"] = {"default": default_model}
    return AgentPack(
        agent_id=agent_id,
        root_dir=Path(f"/tmp/{agent_id}"),
        spec=AgentSpec.model_validate(spec_data),
        agents_md_path=Path(f"/tmp/{agent_id}/AGENTS.md"),
        agents_md_text="",
        agents_md_sha256="0" * 64,
    )


def _catalog() -> AgentCatalog:
    packs = {
        "main": _pack("main", default_model="gpt-default"),
        "worker": _pack("worker"),
        "hidden": _pack("hidden", exposed=False),
    }
    return AgentCatalog(packs=packs, root_dir=Path("/tmp/.agents/agents"))


def test_prepare_responses_request_context_resolves_agent_session_and_thread() -> None:
    body = {
        "metadata": {
            "session_key": "session-1",
            "thread_id": "thr_child",
            "thread_depth": 2,
        },
        "stream": True,
    }
    ctx = prepare_responses_request_context(
        body=body,
        metadata=body["metadata"],
        headers={"x-agent-id": "worker", "idempotency-key": " idem-1 "},
        catalog=_catalog(),
    )

    assert ctx.agent_id == "worker"
    assert ctx.pack.agent_id == "worker"
    assert ctx.session_key == "session-1"
    assert ctx.session_partition_key == "worker::session-1"
    assert ctx.stream is True
    assert ctx.thread_id == "thr_child"
    assert ctx.thread_depth == 2
    assert ctx.idempotency_key == "idem-1"
    assert "model" not in ctx.body


def test_prepare_responses_request_context_metadata_agent_and_default_model() -> None:
    body = {"metadata": {"agent_id": "main"}}
    ctx = prepare_responses_request_context(
        body=body,
        metadata=body["metadata"],
        headers={"x-agent-id": "worker"},
        catalog=_catalog(),
        ephemeral_session_key_factory=lambda: "ephemeral::fixed",
    )

    assert ctx.agent_id == "main"
    assert ctx.session_key == "ephemeral::fixed"
    assert ctx.session_partition_key == "main::ephemeral::fixed"
    assert ctx.body["model"] == "gpt-default"
    assert ctx.thread_id == ctx.root_thread_id
    assert ctx.thread_depth == 0


def test_prepare_responses_request_context_rejects_unknown_hidden_and_long_idempotency() -> None:
    for body, headers, expected_status, expected_message in [
        ({"metadata": {"agent_id": "missing"}}, {}, 404, "unknown agent_id: missing"),
        ({"metadata": {"agent_id": "hidden"}}, {}, 403, "agent_id not exposed: hidden"),
        ({}, {"idempotency-key": "x" * 257}, 400, "Idempotency-Key too long (max 256)"),
    ]:
        try:
            prepare_responses_request_context(
                body=body,
                metadata=body.get("metadata"),
                headers=headers,
                catalog=_catalog(),
            )
        except ResponsesRequestContextError as exc:
            assert exc.status_code == expected_status
            assert exc.message == expected_message
        else:
            raise AssertionError("expected ResponsesRequestContextError")
