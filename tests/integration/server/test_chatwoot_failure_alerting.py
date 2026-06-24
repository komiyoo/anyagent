from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import httpx

from anyagent.observability import get_observability_emitter
from anyagent.server.app import create_app


ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PLUGIN_ROOT = ROOT / "packages" / "anyagent" / "src" / "anyagent" / "plugins" / "builtin"


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


def test_chatwoot_platform_event_persist_failure_emits_warning(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_platform_event_persist_failure_emits_warning(tmp_path, monkeypatch))


async def _run_chatwoot_platform_event_persist_failure_emits_warning(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("ANYAGENT_CHATWOOT_CREDENTIAL_KIND", "webhook_secret")

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    state = app.state.anyagent

    # Force the platform-event append to fail so the warning path is exercised.
    async def _raising_append(*, response_id: str, event: str | None, data: str) -> int:
        raise RuntimeError("persist boom")

    monkeypatch.setattr(state.events, "append", _raising_append)

    emitter = get_observability_emitter()
    emitter.add_sink(state.telemetry_observability_sink)
    try:
        payload = {
            "event": "conversation_resolved",
            "timestamp": 1717000000,
            "account": {"id": 1},
            "conversation": {"id": 42},
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            b"test-chatwoot-secret",
            f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            response = await http.post(
                "/gateway/chatwoot/webhook",
                headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
                content=raw_body,
            )

        # The webhook still acknowledges (platform event persistence is best-effort).
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # ... but a warning observability event must be emitted instead of the
        # failure being silently swallowed.
        events = await state.telemetry_event_store.list()
        warnings = [event for event in events if event.type == "chatwoot.platform_event.persist_failed"]
        assert len(warnings) == 1
        assert warnings[0].level == "warning"
        assert warnings[0].payload.get("event_name") == "conversation_resolved"
        assert warnings[0].payload.get("session_key") == "chatwoot:1:42"
        assert "persist boom" in warnings[0].payload.get("reason", "")
    finally:
        emitter.remove_sink(state.telemetry_observability_sink)
