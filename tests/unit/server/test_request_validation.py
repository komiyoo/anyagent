from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from anyagent.server.app import create_app
from anyagent.server.config.request_validation import (
    ResponsesRequestValidationError,
    ensure_metadata_object,
    ensure_request_body_object,
    parse_function_tools,
)


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
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


def test_ensure_request_body_object_rejects_non_object() -> None:
    try:
        ensure_request_body_object([])
    except ResponsesRequestValidationError as exc:
        assert str(exc) == "request body must be an object"
    else:
        raise AssertionError("expected ResponsesRequestValidationError")


def test_ensure_metadata_object_rejects_non_object() -> None:
    try:
        ensure_metadata_object({"metadata": "bad"})
    except ResponsesRequestValidationError as exc:
        assert str(exc) == "metadata must be an object"
    else:
        raise AssertionError("expected ResponsesRequestValidationError")


def test_parse_function_tools_parses_valid_tools() -> None:
    parsed = parse_function_tools(
        [
            {
                "type": "function",
                "name": "core.echo",
                "description": "echo",
                "parameters": {"type": "object", "properties": {}},
                "strict": True,
            }
        ]
    )
    assert parsed is not None
    assert parsed[0].name == "core.echo"


def test_parse_function_tools_rejects_invalid_items() -> None:
    try:
        parse_function_tools([{"type": "function"}])
    except ResponsesRequestValidationError as exc:
        assert str(exc).startswith("invalid tools[0]:")
    else:
        raise AssertionError("expected ResponsesRequestValidationError")


def test_builtin_server_request_validation_path() -> None:
    with tempfile.TemporaryDirectory(prefix="anyagent-request-validation-") as td:
        workspace_dir = Path(td)
        _write_workspace(workspace_dir)
        app = create_app(workspace_dir=workspace_dir, api_key="user-key", sandbox_root_dir=workspace_dir / ".sandbox")

        headers = {"Authorization": "Bearer user-key", "Content-Type": "application/json"}
        with TestClient(app) as client:
            r1 = client.post("/v1/responses", headers=headers, content="{")
            assert r1.status_code == 400, r1.text
            assert r1.json()["detail"] == "invalid JSON body"

            r2 = client.post("/v1/responses", headers=headers, json=[])
            assert r2.status_code == 400, r2.text
            assert r2.json()["detail"] == "request body must be an object"

            r3 = client.post("/v1/responses", headers=headers, json={"model": "gpt-4o-mini", "metadata": "bad"})
            assert r3.status_code == 400, r3.text
            assert r3.json()["detail"] == "metadata must be an object"

            r4 = client.post("/v1/responses", headers=headers, json={"model": "gpt-4o-mini", "tools": {}})
            assert r4.status_code == 400, r4.text
            assert r4.json()["detail"] == "tools must be a list"

            r5 = client.post(
                "/v1/responses",
                headers=headers,
                json={"model": "gpt-4o-mini", "tools": [{"type": "function"}]},
            )
            assert r5.status_code == 400, r5.text
            assert r5.json()["detail"].startswith("invalid tools[0]:")
