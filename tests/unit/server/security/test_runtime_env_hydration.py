from __future__ import annotations

import os
from pathlib import Path

from anyagent.server.runtime.workspace_env import (
    last_runtime_env_hydration,
    load_workspace_runtime_environment,
    runtime_env_bindings,
)


def _write_runtime_env(tmp_path: Path, *, overwrite: bool) -> None:
    config_path = tmp_path / ".anyagent" / "anyagent.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    overwrite_line = "      overwrite: true\n" if overwrite else ""
    config_path.write_text(
        "\n".join(
            [
                "credentials:",
                "  backend: env",
                "  runtime_env:",
                "    - name: AMAP_MAPS_API_KEY",
                "      credential_id: amap_maps_api_key",
                "      kind: api_key",
                overwrite_line.rstrip("\n"),
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )


def test_hydration_records_name_and_credential_id_without_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CREDENTIAL__AMAP_MAPS_API_KEY", "amap-secret")
    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    _write_runtime_env(tmp_path, overwrite=False)

    config = load_workspace_runtime_environment(tmp_path)
    records = last_runtime_env_hydration()

    assert os.environ["AMAP_MAPS_API_KEY"] == "amap-secret"
    assert len(records) == 1
    assert records[0].name == "AMAP_MAPS_API_KEY"
    assert records[0].credential_id == "amap_maps_api_key"
    assert records[0].applied is True
    assert "amap-secret" not in repr(records)
    bindings = runtime_env_bindings(config)
    assert [(item.name, item.credential_id, item.applied) for item in bindings] == [
        ("AMAP_MAPS_API_KEY", "amap_maps_api_key", False)
    ]
    assert "amap-secret" not in repr(bindings)


def test_hydration_skips_existing_env_unless_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CREDENTIAL__AMAP_MAPS_API_KEY", "vault-secret")
    monkeypatch.setenv("AMAP_MAPS_API_KEY", "existing")
    _write_runtime_env(tmp_path, overwrite=False)

    load_workspace_runtime_environment(tmp_path)
    skipped = last_runtime_env_hydration()

    assert os.environ["AMAP_MAPS_API_KEY"] == "existing"
    assert skipped[0].applied is False
    assert "vault-secret" not in repr(skipped)

    _write_runtime_env(tmp_path, overwrite=True)
    load_workspace_runtime_environment(tmp_path)
    replaced = last_runtime_env_hydration()

    assert os.environ["AMAP_MAPS_API_KEY"] == "vault-secret"
    assert replaced[0].applied is True
    assert "vault-secret" not in repr(replaced)
