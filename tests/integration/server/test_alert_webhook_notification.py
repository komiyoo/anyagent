from __future__ import annotations

import asyncio
import json
from pathlib import Path

from anyagent.observability import emit_observability_event, get_observability_emitter
from anyagent.server.app import create_app


ROOT = Path(__file__).resolve().parents[3]


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


class _RecordingAsyncClient:
    """Stand-in for httpx.AsyncClient that records outbound POSTs."""

    def __init__(self, posts: list[dict]) -> None:
        self._posts = posts

    async def __aenter__(self) -> _RecordingAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    async def post(self, url: str, *, headers: dict | None = None, json: object = None) -> object:
        self._posts.append({"url": url, "headers": dict(headers or {}), "json": json})
        return type("Response", (), {"status_code": 200, "text": "ok"})()


def test_alert_webhook_feishu_payload_on_error_event(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_alert_webhook_feishu_payload_on_error_event(tmp_path, monkeypatch))


async def _run_alert_webhook_feishu_payload_on_error_event(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.feishu.example/abc")
    monkeypatch.setenv("ALERT_WEBHOOK_FORMAT", "feishu")
    monkeypatch.setenv(
        "ALERT_WEBHOOK_HEADERS",
        json.dumps({"Authorization": "Bearer tok"}),
    )

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    # The webhook channel must be attached to the built-in error rule.
    rules = {rule.rule_id: rule for rule in await state.alert_store.list_rules()}
    error_rule = rules["builtin.server_error"]
    assert len(error_rule.channels) == 1
    channel = error_rule.channels[0]
    assert channel.url == "https://hooks.feishu.example/abc"
    assert channel.format == "feishu"
    assert channel.headers == {"Authorization": "Bearer tok"}

    # Wire the telemetry sink so emitted observability events surface in the
    # timeline the alert evaluator queries (mirrors the app lifespan).
    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        posts: list[dict] = []
        monkeypatch.setattr(
            "anyagent.server.persistence.alerts.httpx.AsyncClient",
            lambda *args, **kwargs: _RecordingAsyncClient(posts),
        )

        emit_observability_event(
            "server.response.nonstream.failed",
            category="server",
            level="error",
            payload={
                "response_id": "resp_429_1",
                "agent_id": "main",
                "session_key": "chatwoot:1:42",
                "status_code": 429,
                "error_type": "RateLimitError",
            },
        )

        created = await state.alert_evaluator.evaluate_once()
        assert created, "alert evaluator should create an alert for the error event"
        assert len(posts) == 1, "exactly one feishu webhook POST expected"

        post = posts[0]
        assert post["url"] == "https://hooks.feishu.example/abc"
        assert post["headers"]["Authorization"] == "Bearer tok"
        assert post["json"]["msg_type"] == "text"
        text = post["json"]["content"]["text"]
        assert "server.response.nonstream.failed" in text
        assert "severity=error" in text
        assert "agent_id=main" in text
        assert "session_key=chatwoot:1:42" in text
        assert "status_code=429" in text
        assert "error_type=RateLimitError" in text
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)


def test_no_alert_webhook_url_is_backward_compatible(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_no_alert_webhook_url_is_backward_compatible(tmp_path, monkeypatch))


async def _run_no_alert_webhook_url_is_backward_compatible(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    # No webhook configured -> error rule has no channels (no-op fan-out).
    rules = {rule.rule_id: rule for rule in await state.alert_store.list_rules()}
    assert rules["builtin.server_error"].channels == []

    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        posts: list[dict] = []
        monkeypatch.setattr(
            "anyagent.server.persistence.alerts.httpx.AsyncClient",
            lambda *args, **kwargs: _RecordingAsyncClient(posts),
        )
        emit_observability_event(
            "server.response.nonstream.failed",
            category="server",
            level="error",
            payload={"response_id": "resp_x", "status_code": 500},
        )
        created = await state.alert_evaluator.evaluate_once()
        # An alert is still created in-memory, but no webhook fires (no channel).
        assert created
        assert posts == [], "no webhook POST should fire without a configured URL"
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)


def test_quota_exhausted_feishu_payload_includes_project_and_channel(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_quota_exhausted_feishu_payload_includes_project_and_channel(tmp_path, monkeypatch))


async def _run_quota_exhausted_feishu_payload_includes_project_and_channel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.feishu.example/abc")
    monkeypatch.setenv("ALERT_WEBHOOK_FORMAT", "feishu")
    monkeypatch.setenv("PROJECT", "lt-anyagent-wks")

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent
    rules = {rule.rule_id: rule for rule in await state.alert_store.list_rules()}
    assert len(rules["builtin.quota_exhausted"].channels) == 1

    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        posts: list[dict] = []
        monkeypatch.setattr(
            "anyagent.server.persistence.alerts.httpx.AsyncClient",
            lambda *args, **kwargs: _RecordingAsyncClient(posts),
        )
        emit_observability_event(
            "provider.quota_exhausted",
            category="server",
            level="error",
            payload={
                "project": "lt-anyagent-wks",
                "channel": "jina",
                "status_code": 402,
                "error_type": "quota_exhausted",
                "message": "credits exceeded",
            },
        )
        created = await state.alert_evaluator.evaluate_once()
        assert created
        assert len(posts) == 1
        text = posts[0]["json"]["content"]["text"]
        assert "Resource quota exhausted" in text
        assert "project=lt-anyagent-wks" in text
        assert "channel=jina" in text
        assert "event_type=provider.quota_exhausted" in text
        assert "status_code=402" in text
        assert "credits exceeded" in text
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)


def test_global_exception_handler_emits_unhandled_event(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    @app.get("/_test/raise")
    async def _raise() -> None:  # noqa: ANN202
        raise RuntimeError("boom")

    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        # TestClient (with raise_server_exceptions=False) surfaces the 500 the
        # handler returns; httpx.ASGITransport would re-raise the original
        # exception instead, which is a test-harness artifact.
        from starlette.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/_test/raise")
            unauth = client.get("/admin/plugins/catalog")

        assert response.status_code == 500
        assert response.json()["error"]["type"] == "server_error"
        # HTTPException routing must remain intact: a 401 still surfaces.
        assert unauth.status_code == 401

        events = asyncio.run(state.telemetry_event_store.list())
        unhandled = next(event for event in events if event.type == "server.unhandled_exception")
        assert unhandled.payload.get("error_type") == "RuntimeError"
        assert unhandled.payload.get("path") == "/_test/raise"
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)
