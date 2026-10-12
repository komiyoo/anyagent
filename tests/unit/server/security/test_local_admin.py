from __future__ import annotations

from pathlib import Path

import pytest

from anyagent.config.schema import CredentialsConfig, CredentialsFileConfig
from anyagent.protocol.credential_vault import AdminCredentialSetRequest, CredentialScope
from anyagent.server.security.local_admin import (
    CredentialAdminError,
    local_delete_credential,
    local_list_credentials,
    local_set_credential,
)


def _request(value: str = "super-secret-value") -> AdminCredentialSetRequest:
    return AdminCredentialSetRequest(
        credential_id="cred_api",
        kind="bearer_token",
        value=value,
        scope=CredentialScope(level="agent", agent_id="main"),
        metadata={"provider": "test"},
    )


def _file_config(*, writable: bool) -> CredentialsConfig:
    return CredentialsConfig(
        backend="file",
        writable=writable,
        file=CredentialsFileConfig(root=".anyagent/credentials"),
    )


def test_local_file_backend_roundtrip_does_not_return_values(tmp_path: Path) -> None:
    config = _file_config(writable=True)
    ref = local_set_credential(config, tmp_path, _request())

    assert ref.credential_id == "cred_api"
    assert "super-secret-value" not in ref.model_dump_json()

    listed = local_list_credentials(config, tmp_path)
    payload = listed.model_dump_json()
    assert "super-secret-value" not in payload
    assert listed.credentials[0].credential_id == "cred_api"
    assert listed.credentials[0].metadata == {"provider": "test"}

    deleted = local_delete_credential(config, tmp_path, "cred_api")
    assert deleted.deleted is True
    assert local_list_credentials(config, tmp_path).credentials == []


def test_local_admin_rejects_none_and_read_only(tmp_path: Path) -> None:
    with pytest.raises(CredentialAdminError, match="none"):
        local_set_credential(CredentialsConfig(backend="none"), tmp_path, _request())
    with pytest.raises(CredentialAdminError, match="none"):
        local_list_credentials(CredentialsConfig(backend="none"), tmp_path)
    with pytest.raises(CredentialAdminError, match="none"):
        local_delete_credential(CredentialsConfig(backend="none"), tmp_path, "cred_api")

    read_only = _file_config(writable=False)
    with pytest.raises(CredentialAdminError, match="writable"):
        local_set_credential(read_only, tmp_path, _request())
    with pytest.raises(CredentialAdminError, match="writable"):
        local_delete_credential(read_only, tmp_path, "cred_api")

    listed = local_list_credentials(read_only, tmp_path)
    assert listed.credentials == []
    assert "super-secret-value" not in listed.model_dump_json()
