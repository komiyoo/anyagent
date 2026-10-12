from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from anyagent.config.schema import (
    CredentialsConfig,
    CredentialsDbConfig,
    CredentialsFileConfig,
    CredentialsInfisicalConfig,
    CredentialsVaultConfig,
    plain_secret,
)
from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_backends import (
    DatabaseBackendConfig,
    InfisicalBackendConfig,
    ReadOnlyCredentialStoreError,
    VaultBackendConfig,
)
from anyagent.server.security.credential_runtime import build_credential_store


def test_credentials_config_repr_hides_secret_values() -> None:
    config = CredentialsConfig(
        backend="vault",
        db=CredentialsDbConfig(
            dsn=SecretStr("postgresql://user:db-password-value@localhost/db"),
            encryption_key=SecretStr("encryption-key-value"),
        ),
        vault=CredentialsVaultConfig(addr="https://vault.example", token=SecretStr("vault-token-value")),
        infisical=CredentialsInfisicalConfig(
            client_id="client-id",
            client_secret=SecretStr("client-secret-value"),
            token=SecretStr("infisical-token-value"),
        ),
    )

    text = f"{config!r} {config}"
    for secret in (
        "db-password-value",
        "encryption-key-value",
        "vault-token-value",
        "client-secret-value",
        "infisical-token-value",
    ):
        assert secret not in text
    assert plain_secret(config.db.encryption_key) == "encryption-key-value"
    assert plain_secret(config.vault.token) == "vault-token-value"
    assert plain_secret(config.infisical.client_secret) == "client-secret-value"
    assert plain_secret(config.infisical.token) == "infisical-token-value"
    assert plain_secret(config.db.dsn) == "postgresql://user:db-password-value@localhost/db"


def test_backend_config_repr_hides_secrets() -> None:
    database = DatabaseBackendConfig(
        postgres_dsn="postgresql://user:pass@localhost/db",
        encryption_key="key-value",
    )
    vault = VaultBackendConfig(base_url="https://vault.example", token="vault-token-value")
    infisical = InfisicalBackendConfig(
        host="https://app.infisical.test",
        client_id="client-id",
        client_secret="client-secret-value",
        project_id="project",
        environment="dev",
        credential_root_path="/anyagent/credentials",
        token="infisical-token-value",
    )

    database_text = repr(database)
    assert "pass" not in database_text
    assert "key-value" not in database_text
    assert "vault-token-value" not in repr(vault)
    infisical_text = repr(infisical)
    assert "client-secret-value" not in infisical_text
    assert "infisical-token-value" not in infisical_text
    assert "client-id" in infisical_text


def test_writable_false_rejects_set_and_still_resolves() -> None:
    store = build_credential_store(
        CredentialsConfig(backend="env", writable=False),
        environ={"CREDENTIAL__CRED_API": "env-secret"},
    )
    assert store is not None

    async def _run() -> None:
        with pytest.raises(ReadOnlyCredentialStoreError, match="writable"):
            await store.set(
                credential_id="cred_api",
                kind="api_key",
                value="new-secret",
                scope=CredentialScope(level="global"),
            )
        with pytest.raises(ReadOnlyCredentialStoreError, match="writable"):
            await store.delete("cred_api")
        resolved = await store.resolve(AuthRef(kind="api_key", ref="cred_api"))
        assert resolved == "env-secret"

    asyncio.run(_run())


def test_file_write_suffix_is_not_a_backend() -> None:
    config = CredentialsConfig.model_construct(
        backend="file-write",
        writable=True,
        file=CredentialsFileConfig(),
        db=CredentialsConfig().db,
        vault=CredentialsConfig().vault,
        infisical=CredentialsConfig().infisical,
        runtime_env=[],
    )
    with pytest.raises(RuntimeError, match="unsupported credential store backend"):
        build_credential_store(config)
