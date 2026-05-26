from __future__ import annotations

import os
from pathlib import Path

from anyagent.server.workspace_env import load_workspace_runtime_environment


def test_workspace_runtime_env_projects_only_listed_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CREDENTIAL__AMAP_MAPS_API_KEY", "amap-secret")
    monkeypatch.setenv("CREDENTIAL__OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("CREDENTIAL__UNLISTED_SECRET", "do-not-project")
    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("UNLISTED_SECRET", raising=False)

    secrets_path = tmp_path / ".agents" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text(
        "\n".join(
            [
                "credential_vault:",
                "  backend: env",
                "runtime_env:",
                "  - name: AMAP_MAPS_API_KEY",
                "    credential_id: amap_maps_api_key",
                "    kind: api_key",
                "  - name: OPENAI_API_KEY",
                "    credential_id: openai_api_key",
                "    kind: api_key",
                "",
            ]
        ),
        encoding="utf-8",
    )

    load_workspace_runtime_environment(tmp_path)

    assert os.environ["AMAP_MAPS_API_KEY"] == "amap-secret"
    assert os.environ["OPENAI_API_KEY"] == "openai-secret"
    assert "UNLISTED_SECRET" not in os.environ


def test_workspace_runtime_env_keeps_existing_env_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CREDENTIAL__AMAP_MAPS_API_KEY", "vault-secret")
    monkeypatch.setenv("AMAP_MAPS_API_KEY", "existing")

    secrets_path = tmp_path / ".agents" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text(
        "\n".join(
            [
                "credential_vault:",
                "  backend: env",
                "runtime_env:",
                "  - name: AMAP_MAPS_API_KEY",
                "    credential_id: amap_maps_api_key",
                "    kind: api_key",
                "",
            ]
        ),
        encoding="utf-8",
    )

    load_workspace_runtime_environment(tmp_path)

    assert os.environ["AMAP_MAPS_API_KEY"] == "existing"
