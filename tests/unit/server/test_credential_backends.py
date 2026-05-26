from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_backends import (
    EnvBackend,
    FileBackend,
    InfisicalBackend,
    InfisicalBackendConfig,
    ReadOnlyCredentialStoreError,
)
from anyagent.server.security.credential_runtime import (
    CredentialRuntimeConfig,
    build_credential_resolver_from_config,
    build_credential_store_from_config,
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
    def __init__(self, *, host: str, cache_ttl: int) -> None:
        self.auth = SimpleNamespace(universal_auth=_FakeUniversalAuth())
        self.secrets = _FakeSecrets()


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


def test_credential_store_builder_selects_env_file_and_validates_infisical(tmp_path: Path) -> None:
    env_store = build_credential_store_from_config(CredentialRuntimeConfig(backend="env"))
    file_store = build_credential_store_from_config(
        CredentialRuntimeConfig(
            backend="file",
            file_root=".agents/credentials",
            workspace_dir=tmp_path,
        )
    )

    assert isinstance(env_store, EnvBackend)
    assert isinstance(file_store, FileBackend)
    assert resolve_credential_file_root(
        CredentialRuntimeConfig(
            backend="file",
            file_root=".agents/credentials",
            workspace_dir=tmp_path,
        )
    ) == tmp_path / ".agents" / "credentials"
    with pytest.raises(RuntimeError, match="INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"):
        build_credential_store_from_config(CredentialRuntimeConfig(backend="infisical"))
    with pytest.raises(RuntimeError, match="unsupported credential store backend"):
        build_credential_store_from_config(CredentialRuntimeConfig(backend="unknown"))


def test_credential_resolver_builder_keeps_core_write_alias_and_memory_fallback(tmp_path: Path) -> None:
    fallback = build_credential_resolver_from_config(
        CredentialRuntimeConfig(
            backend="none",
            workspace_dir=tmp_path,
        )
    )
    writable = build_credential_resolver_from_config(
        CredentialRuntimeConfig(
            backend="file-write",
            file_root=".agents/credentials",
            workspace_dir=tmp_path,
        )
    )
    disabled = build_credential_resolver_from_config(
        CredentialRuntimeConfig(
            backend="none",
            workspace_dir=tmp_path,
        ),
        fallback_to_memory=False,
    )

    assert isinstance(fallback, InMemoryCredentialStore)
    assert isinstance(writable, FileBackend)
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
