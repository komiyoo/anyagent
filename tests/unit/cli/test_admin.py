from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyagent.cli import main
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.plugins import PluginCatalogResponse


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self.text = "{}"
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_plugin_catalog_reads_admin_api(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[dict] = []

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _Response(
            {
                "plugin_roots": ["/workspace/plugins"],
                "loaded": [
                    {
                        "plugin_id": "demo",
                        "description": "Demo connector.",
                        "channels": ["demo"],
                        "plugin_dir": "/workspace/plugins/demo",
                        "entrypoint": "plugin.py:register",
                        "tools": [
                            {
                                "name": "demo.echo",
                                "category": "channel",
                                "kind": "command",
                                "description": "Echo text.",
                            }
                        ],
                        "cite": {
                            "manifest": "/workspace/plugins/demo/plugin.json",
                            "entrypoint": "/workspace/plugins/demo/plugin.py",
                        },
                        "docs": ["/workspace/plugins/demo/README.md"],
                        "schemas": ["/workspace/plugins/demo/schemas/config.schema.json"],
                        "tests": ["/workspace/plugins/demo/tests/smoke.py"],
                    }
                ],
                "errors": [],
            }
        )

    monkeypatch.setattr("anyagent.cli.admin_client.httpx.get", fake_get)

    rc = main(
        [
            "plugin",
            "catalog",
            "--admin-url",
            "http://tool-runtime.local",
            "--admin-key",
            "admin-key",
        ]
    )

    assert rc == 0
    assert calls == [
        {
            "url": "http://tool-runtime.local/admin/plugins/catalog",
            "headers": {"Authorization": "Bearer admin-key"},
            "timeout": 15.0,
        }
    ]
    payload = PluginCatalogResponse.model_validate(json.loads(capsys.readouterr().out))
    assert payload.plugin_roots == ["/workspace/plugins"]
    assert payload.loaded[0].plugin_id == "demo"
    assert payload.loaded[0].tools[0].name == "demo.echo"
    assert payload.loaded[0].docs == ["/workspace/plugins/demo/README.md"]


def test_storage_health_reads_typed_admin_api(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[dict] = []

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _Response(_storage_health_payload())

    monkeypatch.setattr("anyagent.cli.admin_client.httpx.get", fake_get)

    rc = main(
        [
            "storage",
            "health",
            "--admin-url",
            "http://agent-api.local",
            "--admin-key",
            "admin-key",
        ]
    )

    assert rc == 0
    assert calls == [
        {
            "url": "http://agent-api.local/admin/storage/health",
            "headers": {"Authorization": "Bearer admin-key"},
            "timeout": 15.0,
        }
    ]
    payload = StorageHealthResponse.model_validate(json.loads(capsys.readouterr().out))
    assert payload.ok is True
    assert payload.backends.event_store == "memory"
    assert payload.postgres.configured is False


def test_storage_health_resolves_admin_key_from_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict] = []

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _Response(_storage_health_payload())

    monkeypatch.setattr("anyagent.cli.admin_client.httpx.get", fake_get)
    monkeypatch.setenv("ADMIN_API_KEY", "from-config")

    rc = main(["storage", "health", "--workspace", str(tmp_path)])

    assert rc == 0
    assert calls[0]["url"] == "http://127.0.0.1:8787/admin/storage/health"
    assert calls[0]["headers"] == {"Authorization": "Bearer from-config"}
    assert capsys.readouterr().out


def test_credential_import_reads_value_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[dict] = []
    manifest = tmp_path / "credentials.yaml"
    manifest.write_text(
        "\n".join(
            [
                "credentials:",
                "  - credential_id: demo",
                "    kind: api_key",
                "    scope:",
                "      level: global",
                "    value_from_env: DEMO_SECRET",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_post(url, *, headers, json, timeout):  # noqa: A002
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response(
            {
                "credential_id": json["credential_id"],
                "kind": json["kind"],
                "scope": json["scope"],
                "metadata": json.get("metadata") or {},
            }
        )

    monkeypatch.setattr("anyagent.cli.admin_client.httpx.post", fake_post)
    monkeypatch.setenv("DEMO_SECRET", "from-env")

    rc = main(
        [
            "credential",
            "import",
            "--file",
            str(manifest),
            "--admin-url",
            "http://agent-api.local",
            "--admin-key",
            "admin-key",
        ]
    )

    assert rc == 0
    assert calls[0]["json"]["value"] == "from-env"
    assert json.loads(capsys.readouterr().out) == {"ok": True, "set": 1, "skipped": 0, "dry_run": False}


def test_storage_migrate_returns_nonzero_on_runtime_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(**kwargs):
        raise RuntimeError("postgres dsn is missing")

    monkeypatch.setattr("anyagent.cli.storage.apply_storage_migrations", boom)

    rc = main(["storage", "migrate"])

    assert rc == 1
    assert "postgres dsn is missing" in capsys.readouterr().err


def test_storage_replay_prints_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "anyagent.cli.storage.replay_rollout_records",
        lambda **kwargs: {"summary": {"count": 0}, "records": []},
    )

    rc = main(["storage", "replay", "--root-dir", str(tmp_path)])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["count"] == 0
    assert payload["records"] == []


def test_alembic_scripts_live_under_storage() -> None:
    from anyagent.cli.storage import _alembic_dir

    assert (_alembic_dir() / "env.py").is_file()


def test_db_current_without_dsn_returns_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("alembic")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))

    rc = main(["db", "current"])

    assert rc == 1
    assert "DATABASE_URL or POSTGRES_DSN must be set" in capsys.readouterr().err


def _storage_health_payload() -> dict:
    return {
        "ok": True,
        "storage_mode": "none",
        "backends": {
            "event_store": "memory",
            "run_store": "memory",
            "session_store": "memory",
            "session_lock": "local",
        },
        "retention_s": {"events": 86400, "runs": 86400, "sessions": 86400},
        "stores": {"events": {"type": "memory", "layers": ["process"]}},
        "capabilities": {
            "events": {
                "tier": "reference",
                "source_of_truth": "packages/anyagent/src/anyagent/storage",
                "requires_services": [],
                "restart_recovery": False,
                "cross_instance": False,
                "supports_replay": True,
                "supports_live_tail": True,
            }
        },
        "postgres": {"configured": False, "reachable": None, "schema": None},
        "redis": {"configured": False, "reachable": None, "namespace": None},
    }
