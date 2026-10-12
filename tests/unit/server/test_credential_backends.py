from __future__ import annotations

import asyncio
import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from anyagent.config.schema import CredentialsConfig, CredentialsFileConfig
from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_backends import (
    DatabaseBackend,
    DatabaseBackendConfig,
    EnvBackend,
    FileBackend,
    InfisicalBackend,
    InfisicalBackendConfig,
    ReadOnlyCredentialStore,
    ReadOnlyCredentialStoreError,
    VaultBackend,
    VaultBackendConfig,
)
from anyagent.server.security.credential_runtime import (
    build_credential_store,
    open_process_credential_store,
    resolve_credential_file_root,
)
from anyagent.server.security.credential_store import InMemoryCredentialStore


class _FakeUniversalAuth:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def login(self, client_id: str, client_secret: str) -> None:
        self.calls.append((client_id, client_secret))


class _FakeSecrets:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.list_items: list[SimpleNamespace] = []

    def get_secret_by_name(
        self,
        secret_name: str,
        environment_slug: str,
        secret_path: str,
        *,
        project_id: str | None = None,
        include_imports: bool = False,
        expand_secret_references: bool = True,
        view_secret_value: bool = True,
    ) -> SimpleNamespace:
        key = (secret_path, secret_name)
        if key not in self.values:
            raise RuntimeError("404 not found")
        return SimpleNamespace(secretValue=self.values[key])

    def list_secrets(
        self,
        environment_slug: str,
        secret_path: str,
        *,
        project_id: str | None = None,
        recursive: bool = False,
        include_imports: bool = False,
        expand_secret_references: bool = False,
        view_secret_value: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(secrets=list(self.list_items))


class _FakeClient:
    def __init__(self, *, host: str, cache_ttl: int, token: str | None = None) -> None:
        self.host = host
        self.cache_ttl = cache_ttl
        self.token = token
        self.auth = SimpleNamespace(universal_auth=_FakeUniversalAuth())
        self.secrets = _FakeSecrets()


class _FakeVaultResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}" if payload is not None else b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"vault http {self.status_code}")

    def json(self) -> dict:
        return dict(self._payload)


class _FakeVaultClient:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    async def request(self, method: str, url: str, *, headers: dict, json: dict | None = None) -> _FakeVaultResponse:
        if method == "POST":
            self.data[url] = dict(json or {})
            return _FakeVaultResponse(204)
        if method == "GET":
            if url not in self.data:
                return _FakeVaultResponse(404)
            return _FakeVaultResponse(200, {"data": self.data[url]})
        if method == "DELETE":
            self.data.pop(url, None)
            return _FakeVaultResponse(204)
        if method == "LIST":
            prefix = url.replace("/metadata/", "/data/").rstrip("/") + "/"
            keys = set()
            for data_url in self.data:
                if not data_url.startswith(prefix):
                    continue
                rest = data_url[len(prefix) :]
                keys.add(rest.split("/", 1)[0] + ("/" if "/" in rest else ""))
            return _FakeVaultResponse(200, {"data": {"keys": sorted(keys)}})
        raise AssertionError(method)


def test_env_backend_prefers_scoped_metadata_env_then_memory() -> None:
    async def _run() -> None:
        environ = {"AGENT_TOKEN": "agent-env-token", "CREDENTIAL__CRED_API": "default-env-token"}
        backend = EnvBackend(environ=environ)
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="global-memory-token",
            scope=CredentialScope(level="global"),
        )
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="agent-memory-token",
            scope=CredentialScope(level="agent", agent_id="main"),
            metadata={"env_var_name": "AGENT_TOKEN"},
        )

        agent_value = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "main"})
        fallback_value = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "other"})
        refs = await backend.list_refs()

        assert agent_value == "agent-env-token"
        assert fallback_value == "default-env-token"
        assert {item["scope"]["level"] for item in refs} == {"agent", "global"}
        assert await backend.delete("cred_api") is True
        assert await backend.delete("cred_api") is False

    asyncio.run(_run())


def test_file_backend_set_list_resolve_delete(tmp_path: Path) -> None:
    async def _run() -> None:
        backend = FileBackend(root=tmp_path / "credentials")
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="global-token",
            scope=CredentialScope(level="global"),
            metadata={"provider": "test"},
        )
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="agent-token",
            scope=CredentialScope(level="agent", agent_id="main"),
        )

        path = tmp_path / "credentials" / "agents" / "main" / "cred_api.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text("utf-8"))["value"] == "agent-token"

        agent_value = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "main"})
        global_value = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "other"})
        refs = await backend.list_refs()
        agent_refs = await backend.list_refs(CredentialScope(level="agent", agent_id="main"))

        assert agent_value == "agent-token"
        assert global_value == "global-token"
        assert len(refs) == 2
        assert len(agent_refs) == 1
        assert agent_refs[0]["scope"] == {"level": "agent", "agent_id": "main"}
        assert await backend.delete("cred_api") is True
        assert await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "main"}) is None

    asyncio.run(_run())


def test_file_backend_supports_session_scope_and_expiration(tmp_path: Path) -> None:
    async def _run() -> None:
        backend = FileBackend(root=tmp_path / "credentials")
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="global-token",
            scope=CredentialScope(level="global"),
        )
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="session-token",
            scope=CredentialScope(level="session", agent_id="main", session_key="thread-1"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            rotate_before=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        await backend.set(
            credential_id="expired_api",
            kind="bearer_token",
            value="expired-token",
            scope=CredentialScope(level="session", agent_id="main", session_key="thread-1"),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        scoped = await backend.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main", "session_key": "thread-1"},
        )
        fallback = await backend.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main", "session_key": "thread-2"},
        )
        expired = await backend.resolve(
            AuthRef(kind="bearer_token", ref="expired_api"),
            scope_context={"agent_id": "main", "session_key": "thread-1"},
        )
        refs = await backend.list_refs(CredentialScope(level="session", agent_id="main", session_key="thread-1"))

        assert scoped == "session-token"
        assert fallback == "global-token"
        assert expired is None
        assert {ref["credential_id"] for ref in refs} == {"cred_api", "expired_api"}
        assert refs[0]["scope"]["level"] == "session"

    asyncio.run(_run())


def test_credential_store_builder_selects_env_file_and_validates_infisical(tmp_path: Path) -> None:
    env_store = build_credential_store(CredentialsConfig(backend="env", writable=True))
    file_store = build_credential_store(
        CredentialsConfig(
            backend="file",
            writable=True,
            file=CredentialsFileConfig(root=".anyagent/credentials"),
        ),
        workspace_dir=tmp_path,
    )

    assert isinstance(env_store, EnvBackend)
    assert isinstance(file_store, FileBackend)
    assert resolve_credential_file_root(".anyagent/credentials", workspace_dir=tmp_path) == (
        tmp_path / ".anyagent" / "credentials"
    )
    with pytest.raises(RuntimeError, match="INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"):
        build_credential_store(CredentialsConfig(backend="infisical", writable=True))
    unknown = CredentialsConfig.model_construct(
        backend="unknown",
        writable=True,
        file=CredentialsFileConfig(),
        db=CredentialsConfig().db,
        vault=CredentialsConfig().vault,
        infisical=CredentialsConfig().infisical,
        runtime_env=[],
    )
    with pytest.raises(RuntimeError, match="unsupported credential store backend"):
        build_credential_store(unknown)


def test_credential_store_none_falls_back_to_memory_and_writable_selects_file(tmp_path: Path) -> None:
    fallback = open_process_credential_store(CredentialsConfig(backend="none"), workspace_dir=tmp_path)
    writable = build_credential_store(
        CredentialsConfig(
            backend="file",
            writable=True,
            file=CredentialsFileConfig(root=".anyagent/credentials"),
        ),
        workspace_dir=tmp_path,
    )
    read_only = build_credential_store(
        CredentialsConfig(
            backend="file",
            writable=False,
            file=CredentialsFileConfig(root=".anyagent/credentials"),
        ),
        workspace_dir=tmp_path,
    )
    disabled = build_credential_store(CredentialsConfig(backend="none"), workspace_dir=tmp_path)

    assert isinstance(fallback, InMemoryCredentialStore)
    assert isinstance(writable, FileBackend)
    assert isinstance(read_only, ReadOnlyCredentialStore)
    assert disabled is None


def test_infisical_backend_resolve_list_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anyagent.server.security.credential_backends._load_infisical_sdk_client", lambda: _FakeClient)
    backend = InfisicalBackend(
        config=InfisicalBackendConfig(
            host="https://app.infisical.test",
            client_id="client-id",
            client_secret="client-secret",
            project_id="project-id",
            environment="dev",
            credential_root_path="/anyagent/credentials",
            cache_ttl_seconds=30,
        )
    )
    fake_client = backend._client
    fake_client.secrets.values[("/anyagent/credentials/global/bearer_token", "cred_api")] = "global-token"
    fake_client.secrets.values[("/anyagent/credentials/agents/main/bearer_token", "cred_api")] = "agent-token"
    fake_client.secrets.list_items = [
        SimpleNamespace(secretKey="cred_global", secretPath="/anyagent/credentials/global/api_key"),
        SimpleNamespace(secretKey="cred_agent", secretPath="/anyagent/credentials/agents/main/bearer_token"),
        SimpleNamespace(secretKey="ignored", secretPath="/other/path"),
    ]

    async def _run() -> None:
        resolved = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "main"})
        fallback = await backend.resolve(AuthRef(kind="bearer_token", ref="cred_api"), scope_context={"agent_id": "other"})
        refs = await backend.list_refs()

        assert resolved == "agent-token"
        assert fallback == "global-token"
        assert refs == [
            {
                "credential_id": "cred_global",
                "kind": "api_key",
                "scope": {"level": "global"},
                "metadata": {
                    "provider": "infisical",
                    "secret_path": "/anyagent/credentials/global/api_key",
                    "environment": "dev",
                    "project_id": "project-id",
                },
            },
            {
                "credential_id": "cred_agent",
                "kind": "bearer_token",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {
                    "provider": "infisical",
                    "secret_path": "/anyagent/credentials/agents/main/bearer_token",
                    "environment": "dev",
                    "project_id": "project-id",
                },
            },
        ]
        with pytest.raises(ReadOnlyCredentialStoreError):
            await backend.set(
                credential_id="cred_api",
                kind="bearer_token",
                value="secret",
                scope=CredentialScope(level="global"),
            )
        with pytest.raises(ReadOnlyCredentialStoreError):
            await backend.delete("cred_api")

    asyncio.run(_run())


def test_infisical_backend_flat_layout_resolves_secret_key_at_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anyagent.server.security.credential_backends._load_infisical_sdk_client", lambda: _FakeClient)
    backend = InfisicalBackend(
        config=InfisicalBackendConfig(
            host="https://app.infisical.test",
            client_id="client-id",
            client_secret="client-secret",
            project_id="project-id",
            environment="dev",
            credential_root_path="/travel-planner-service",
            path_layout="flat",
            cache_ttl_seconds=30,
        )
    )
    fake_client = backend._client
    fake_client.secrets.values[("/travel-planner-service", "OPENAI_API_KEY")] = "openai-token"
    fake_client.secrets.list_items = [
        SimpleNamespace(secretKey="OPENAI_API_KEY", secretPath="/travel-planner-service"),
    ]

    async def _run() -> None:
        resolved = await backend.resolve(AuthRef(kind="api_key", ref="OPENAI_API_KEY"), scope_context={"agent_id": "main"})
        refs = await backend.list_refs()

        assert resolved == "openai-token"
        assert refs == [
            {
                "credential_id": "OPENAI_API_KEY",
                "kind": "secret",
                "scope": {"level": "global"},
                "metadata": {
                    "provider": "infisical",
                    "secret_path": "/travel-planner-service",
                    "environment": "dev",
                    "project_id": "project-id",
                },
            }
        ]

    asyncio.run(_run())


def test_infisical_backend_with_service_token_skips_universal_auth_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anyagent.server.security.credential_backends._load_infisical_sdk_client", lambda: _FakeClient)
    backend = InfisicalBackend(
        config=InfisicalBackendConfig(
            host="https://app.infisical.test",
            client_id="",
            client_secret="",
            token="st.abc123.xyz",
            project_id="project-id",
            environment="dev",
            credential_root_path="/anyagent/credentials",
            cache_ttl_seconds=30,
        )
    )
    fake_client = backend._client
    # Verify the token was passed to the SDK client constructor.
    assert fake_client.token == "st.abc123.xyz"
    # Pre-populate secrets for resolve.
    fake_client.secrets.values[("/anyagent/credentials/global/api_key", "cred_svc")] = "svc-token-value"
    fake_client.secrets.list_items = [
        SimpleNamespace(secretKey="cred_svc", secretPath="/anyagent/credentials/global/api_key"),
    ]

    async def _run() -> None:
        # Resolve should work without calling universal_auth.login.
        resolved = await backend.resolve(AuthRef(kind="api_key", ref="cred_svc"))
        assert resolved == "svc-token-value"

        # _ensure_login should be a no-op for token auth — universal_auth.login MUST NOT be called.
        assert fake_client.auth.universal_auth.calls == []

        refs = await backend.list_refs()
        assert len(refs) == 1
        assert refs[0]["credential_id"] == "cred_svc"

    asyncio.run(_run())


def test_vault_backend_set_resolve_list_and_delete() -> None:
    async def _run() -> None:
        client = _FakeVaultClient()
        backend = VaultBackend(
            config=VaultBackendConfig(base_url="https://vault.test", token="vault-token", root_path="anyagent/credentials"),
            client=client,
        )
        scope = CredentialScope(level="session", agent_id="main", session_key="thread-1")
        await backend.set(
            credential_id="cred_api",
            kind="bearer_token",
            value="session-token",
            scope=scope,
            metadata={"provider": "test"},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        resolved = await backend.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main", "session_key": "thread-1"},
        )
        refs = await backend.list_refs(scope)
        deleted = await backend.delete("cred_api")
        after_delete = await backend.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main", "session_key": "thread-1"},
        )

        assert resolved == "session-token"
        assert refs[0]["credential_id"] == "cred_api"
        assert refs[0]["scope"] == {"level": "session", "agent_id": "main", "session_key": "thread-1"}
        assert deleted is True
        assert after_delete is None

    asyncio.run(_run())


def test_database_backend_requires_encryption_key() -> None:
    with pytest.raises(RuntimeError, match="CREDENTIAL_ENCRYPTION_KEY"):
        DatabaseBackend(config=DatabaseBackendConfig(postgres_dsn="postgresql://user:pass@localhost/db", encryption_key=""))
