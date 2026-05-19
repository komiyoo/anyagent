from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from anyagent.mcp.auth import CredentialResolver, EnvCredentialResolver, FileCredentialResolver, MCPAuthError
from anyagent.protocol.tool_runtime import AuthRef


@dataclass(frozen=True, slots=True)
class InfisicalResolverConfig:
    host: str
    client_id: str
    client_secret: str
    project_id: str
    environment: str
    credential_root_path: str
    cache_ttl_seconds: int = 60


class InfisicalCredentialResolver:
    def __init__(
        self,
        *,
        config: InfisicalResolverConfig,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        try:
            factory = client_factory or _load_infisical_sdk_client()
        except Exception as exc:  # noqa: BLE001
            raise MCPAuthError("infisical credential backend requires installing anyagent[infisical]") from exc

        self._config = config
        self._client = factory(host=config.host, cache_ttl=config.cache_ttl_seconds)
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = ""
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()

        await self._ensure_login()
        candidate_paths = []
        if agent_id:
            candidate_paths.append(self._agent_path(agent_id=agent_id, kind=kind))
        candidate_paths.append(self._global_path(kind=kind))

        for secret_path in candidate_paths:
            try:
                secret = await asyncio.to_thread(
                    self._client.secrets.get_secret_by_name,
                    credential_id,
                    self._config.environment,
                    secret_path,
                    project_id=self._config.project_id,
                    include_imports=False,
                    expand_secret_references=True,
                    view_secret_value=True,
                )
            except Exception as exc:  # noqa: BLE001
                if _looks_like_not_found(exc):
                    continue
                raise MCPAuthError(f"infisical lookup failed: {exc}") from exc

            value = getattr(secret, "secretValue", None)
            if isinstance(value, str) and value:
                return value
        return None

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if self._logged_in:
                return
            try:
                await asyncio.to_thread(
                    self._client.auth.universal_auth.login,
                    self._config.client_id,
                    self._config.client_secret,
                )
            except Exception as exc:  # noqa: BLE001
                raise MCPAuthError(f"infisical universal auth login failed: {exc}") from exc
            self._logged_in = True

    def _normalized_root_path(self) -> str:
        root = (self._config.credential_root_path or "").strip()
        if not root:
            return "/"
        root = root.rstrip("/")
        return root if root.startswith("/") else f"/{root}"

    def _global_path(self, *, kind: str) -> str:
        return f"{self._normalized_root_path()}/global/{kind.strip()}"

    def _agent_path(self, *, agent_id: str, kind: str) -> str:
        return f"{self._normalized_root_path()}/agents/{agent_id.strip()}/{kind.strip()}"


def build_mcp_credential_resolver(
    *,
    backend: str,
    file_root: str,
    environ: dict[str, str] | None = None,
    infisical_host: str | None = None,
    infisical_universal_auth_client_id: str | None = None,
    infisical_universal_auth_client_secret: str | None = None,
    infisical_project_id: str | None = None,
    infisical_environment: str | None = None,
    infisical_cache_ttl_seconds: int = 60,
    infisical_credential_root_path: str = "/anyagent/credentials",
) -> CredentialResolver | None:
    mode = (backend or "").strip().lower()
    if mode in {"", "none"}:
        return None
    if mode == "env":
        return EnvCredentialResolver(environ=environ)
    if mode == "file":
        return FileCredentialResolver(root=file_root, environ=environ)
    if mode == "infisical":
        if not infisical_universal_auth_client_id or not infisical_universal_auth_client_secret:
            raise MCPAuthError("infisical backend requires INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET")
        if not infisical_project_id or not infisical_environment:
            raise MCPAuthError("infisical backend requires INFISICAL_PROJECT_ID and INFISICAL_ENVIRONMENT")
        return InfisicalCredentialResolver(
            config=InfisicalResolverConfig(
                host=(infisical_host or "https://app.infisical.com").strip() or "https://app.infisical.com",
                client_id=infisical_universal_auth_client_id,
                client_secret=infisical_universal_auth_client_secret,
                project_id=infisical_project_id,
                environment=infisical_environment,
                credential_root_path=infisical_credential_root_path,
                cache_ttl_seconds=int(infisical_cache_ttl_seconds),
            )
        )
    raise MCPAuthError(f"unsupported MCP credential backend: {backend}")


def _looks_like_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return "404" in text or "not found" in text


def _load_infisical_sdk_client() -> Callable[..., Any]:
    from infisical_sdk import InfisicalSDKClient

    return InfisicalSDKClient
