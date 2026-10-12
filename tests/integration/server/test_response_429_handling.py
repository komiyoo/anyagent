from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from anyagent.agent_runtime.model_providers.base import ModelProviderUpstreamError
from anyagent.observability import get_observability_emitter
from anyagent.server.app import create_app


def _write_main_agent(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _RateLimitProvider:
    async def create_response(self, *, body, idempotency_key=None, timeout_s=60.0):  # noqa: ANN001
        raise ModelProviderUpstreamError(
            status_code=429,
            body={"error": {"message": "rate limit exceeded", "type": "rate_limit_exceeded"}},
            message="rate limit exceeded",
        )


def test_429_nonstream_emits_failed_event_and_finalizes_run(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_429_nonstream_emits_failed_event_and_finalizes_run(tmp_path, monkeypatch))


async def _run_429_nonstream_emits_failed_event_and_finalizes_run(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: _RateLimitProvider(),
    )

    app = create_app(
              workspace_dir=tmp_path,
              cli_overrides={
                  "server": {
                      "api_key": "user-key",
                      "admin_api_key": "admin-key",
                  },
              },
          )
    state = app.state.anyagent

    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            response = await http.post(
                "/v1/responses",
                headers={"Authorization": "Bearer user-key"},
                json={
                    "input": [{"role": "user", "content": "hi"}],
                    "model": "gpt-4o-mini",
                    "metadata": {"agent_id": "main", "session_key": "s1"},
                },
            )

        # 429 is graded as an error (4xx) and surfaced as the upstream body.
        assert response.status_code == 429
        body = response.json()
        assert body["error"]["type"] == "rate_limit_exceeded"

        # The run must be finalized as failed (not linger in_progress) with the
        # error_json persisted.
        runs = await state.run_store.list(limit=10)
        assert runs, "a run record should exist for the 429 response"
        failed_run = runs[0]
        assert failed_run.effective_status == "failed"
        assert failed_run.status == "errored"
        assert failed_run.error_json == {"message": "rate limit exceeded", "type": "rate_limit_exceeded"}
        assert failed_run.ended_at_ms is not None

        # A server.response.nonstream.failed error event must be emitted.
        events = await state.telemetry_event_store.list()
        failed_events = [event for event in events if event.type == "server.response.nonstream.failed"]
        assert len(failed_events) == 1
        assert failed_events[0].level == "error"
        assert failed_events[0].payload.get("status_code") == 429
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)
