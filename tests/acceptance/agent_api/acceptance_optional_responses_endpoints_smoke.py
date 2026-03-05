from __future__ import annotations

"""Offline smoke for optional `/v1/responses/{id}` query/cancel endpoints."""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from anyagent_agent_api.app import create_app
from anyagent_agent_api.settings import Settings
from anyagent_agent_api.storage.models import RunRecord


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _write_minimal_agent_pack(workspace_dir: Path) -> None:
    """Create one minimal exposed agent for app startup."""

    agent_dir = workspace_dir / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "skills:",
                "  default_selected: []",
                "  disabled_paths: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (agent_dir / "AGENTS.md").write_text("# smoke\n", encoding="utf-8")


def main() -> int:
    """Run optional responses endpoint smoke with in-memory storage."""

    with tempfile.TemporaryDirectory(prefix="anyagent-optional-endpoints-") as td:
        workspace_dir = Path(td)
        _write_minimal_agent_pack(workspace_dir)

        os.environ["WORKSPACE_DIR"] = str(workspace_dir)
        os.environ["AGENT_API_KEY"] = "acceptance-agent-api-key"
        os.environ["OPENAI_API_KEY"] = "acceptance-openai-api-key"
        os.environ["TOOL_RUNTIME_INTERNAL_KEY"] = "acceptance-tool-runtime-key"
        os.environ["STORAGE_MODE"] = "none"

        app = create_app(Settings())
        headers = {"authorization": "Bearer acceptance-agent-api-key"}
        with TestClient(app) as client:
            run_store = app.state.storage.run_store
            run_store._by_response_id["resp_optional_1"] = RunRecord(
                response_id="resp_optional_1",
                session_partition_key="main::optional-smoke",
                idempotency_key="idem_optional_1",
                stream=False,
                status="started",
                last_event_seq=0,
                final_response_json=None,
                error_json=None,
            )

            r1 = client.get("/v1/responses/resp_optional_1", headers=headers)
            _assert(r1.status_code == 200, f"query started run failed: {r1.status_code} {r1.text}")
            _assert(r1.json().get("status") == "in_progress", "started run should be reported as in_progress")

            r2 = client.post("/v1/responses/resp_optional_1/cancel", headers=headers)
            _assert(r2.status_code == 200, f"cancel failed: {r2.status_code} {r2.text}")
            _assert(r2.json().get("status") == "cancelled", "cancel endpoint should return cancelled status")

            r3 = client.get("/v1/responses/resp_optional_1", headers=headers)
            _assert(r3.status_code == 200, f"query after cancel failed: {r3.status_code} {r3.text}")
            _assert(r3.json().get("status") == "cancelled", "query should observe terminal cancelled status")

    print("ok: acceptance_optional_responses_endpoints_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

