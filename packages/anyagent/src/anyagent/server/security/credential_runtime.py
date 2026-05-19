from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from anyagent.mcp.auth import CredentialResolver

from .credential_backends import CredentialStore, EnvBackend, FileBackend, InfisicalBackend, InfisicalBackendConfig
from .credential_store import InMemoryCredentialStore
from .mcp_credentials import build_mcp_credential_resolver


@dataclass(frozen=True, slots=True)
class CredentialRuntimeConfig:
    backend: str = "none"
    file_root: str = ".agents/credentials"
    workspace_dir: str | Path | None = None
    infisical_host: str = "https://app.infisical.com"
    infisical_universal_auth_client_id: str | None = None
    infisical_universal_auth_client_secret: str | None = None
    infisical_project_id: str | None = None
    infisical_environment: str | None = None
    infisical_cache_ttl_seconds: int = 60
    infisical_credential_root_path: str = "/anyagent/credentials"


def build_credential_store_from_config(
    config: CredentialRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> CredentialStore:
    backend = (config.backend or "").strip().lower()
    if backend.endswith("-write"):
        backend = backend.removesuffix("-write")
    if backend.endswith("_write"):
        backend = backend.removesuffix("_write")

    if backend in {"", "env"}:
        return EnvBackend(environ=dict(environ) if environ is not None else None)
    if backend == "file":
        return FileBackend(root=resolve_credential_file_root(config), environ=dict(environ) if environ is not None else None)
    if backend == "infisical":
        return InfisicalBackend(config=_build_infisical_backend_config(config))
    raise RuntimeError(f"unsupported credential store backend: {config.backend}")


def build_credential_resolver_from_config(
    config: CredentialRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    fallback_to_memory: bool = True,
) -> CredentialResolver | None:
    backend = (config.backend or "").strip().lower()
    if backend in {"env-write", "env_write", "file-write", "file_write", "infisical-write", "infisical_write"}:
        return build_credential_store_from_config(config, environ=environ)

    resolver = build_mcp_credential_resolver(
        backend=backend,
        file_root=str(resolve_credential_file_root(config)),
        environ=dict(environ) if environ is not None else None,
        infisical_host=config.infisical_host,
        infisical_universal_auth_client_id=config.infisical_universal_auth_client_id,
        infisical_universal_auth_client_secret=config.infisical_universal_auth_client_secret,
        infisical_project_id=config.infisical_project_id,
        infisical_environment=config.infisical_environment,
        infisical_cache_ttl_seconds=config.infisical_cache_ttl_seconds,
        infisical_credential_root_path=config.infisical_credential_root_path,
    )
    if resolver is not None:
        return resolver
    return InMemoryCredentialStore() if fallback_to_memory else None


def resolve_credential_file_root(config: CredentialRuntimeConfig) -> Path:
    file_root = Path(str(config.file_root or ".agents/credentials")).expanduser()
    if file_root.is_absolute():
        return file_root
    if config.workspace_dir is None:
        return file_root.resolve()
    return Path(config.workspace_dir).expanduser().resolve() / file_root


def _build_infisical_backend_config(config: CredentialRuntimeConfig) -> InfisicalBackendConfig:
    client_id = config.infisical_universal_auth_client_id
    client_secret = config.infisical_universal_auth_client_secret
    project_id = config.infisical_project_id
    environment = config.infisical_environment
    if not client_id or not client_secret:
        raise RuntimeError("infisical backend requires INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET")
    if not project_id or not environment:
        raise RuntimeError("infisical backend requires INFISICAL_PROJECT_ID and INFISICAL_ENVIRONMENT")
    return InfisicalBackendConfig(
        host=(config.infisical_host or "https://app.infisical.com").strip() or "https://app.infisical.com",
        client_id=client_id,
        client_secret=client_secret,
        project_id=project_id,
        environment=environment,
        credential_root_path=config.infisical_credential_root_path,
        cache_ttl_seconds=int(config.infisical_cache_ttl_seconds),
    )

