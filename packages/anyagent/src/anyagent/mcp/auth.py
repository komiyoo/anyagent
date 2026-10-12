from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from anyagent.protocol.tool_runtime import AuthRef

from .models import MCPServerConfig


class MCPAuthError(RuntimeError):
    """Represents authentication resolution failures for MCP server access."""


class CredentialResolver(Protocol):
    """Defines the credential resolution contract used by MCP auth helpers."""

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        """Resolves one credential value for the requested auth reference."""


class EnvCredentialResolver:
    """Resolves credentials from process environment variables."""

    def __init__(self, *, environ: dict[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        """Resolves a credential value using default env fallback convention."""
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = ""
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()

        if agent_id:
            scoped_var = f"CREDENTIAL__{credential_id.upper()}__AGENT__{agent_id.upper()}__{kind.upper()}"
            if scoped_var in self._environ and self._environ[scoped_var]:
                return self._environ[scoped_var]

        default_var = f"CREDENTIAL__{credential_id.upper()}"
        value = self._environ.get(default_var)
        if value:
            return value
        return None


class FileCredentialResolver:
    """Resolves credentials from the same file layout used by Tool Runtime."""

    def __init__(self, *, root: str | Path, environ: dict[str, str] | None = None) -> None:
        self._root = Path(root)
        self._environ = os.environ if environ is None else environ

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        """Resolves a credential value from scoped file entries with env fallback."""
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = ""
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()

        if agent_id:
            agent_path = self._root / "agents" / agent_id / f"{credential_id}.json"
            value = _read_credential_value(agent_path, kind)
            if value is not None:
                return value

        global_path = self._root / "global" / f"{credential_id}.json"
        value = _read_credential_value(global_path, kind)
        if value is not None:
            return value

        default_var = f"CREDENTIAL__{credential_id.upper()}"
        env_value = self._environ.get(default_var)
        if env_value:
            return env_value
        return None


async def resolve_mcp_auth_headers(
    config: MCPServerConfig,
    credential_store: CredentialResolver | None,
    agent_id: str,
) -> dict[str, str]:
    """Resolves auth configuration into HTTP headers for MCP HTTP/SSE transports."""
    headers = dict(config.headers or {})
    if config.auth is None:
        return headers
    if credential_store is None:
        raise MCPAuthError("credential store is not configured")

    injection = (config.auth.injection or "").strip()
    if not injection.startswith("header:"):
        raise MCPAuthError(f"unsupported auth injection target: {injection}")

    ref = AuthRef(kind=config.auth.ref_kind, ref=config.auth.credential_id)
    value = await credential_store.resolve(ref, scope_context={"agent_id": agent_id})
    if value is None:
        raise MCPAuthError(f"credential not found: {config.auth.credential_id}")

    _, header_name = injection.split(":", 1)
    header_name = header_name.strip()
    if not header_name:
        raise MCPAuthError(f"invalid auth injection target: {injection}")

    formatted = config.auth.format.replace("{value}", value)
    headers[header_name] = formatted
    return headers


async def resolve_mcp_auth_env(
    config: MCPServerConfig,
    credential_store: CredentialResolver | None,
    agent_id: str,
    *,
    default_var: str = "ANYAGENT_MCP_AUTH",
) -> dict[str, str]:
    """Resolves auth configuration into environment variables for stdio transport."""
    env = dict(config.env or {})
    if config.auth is None:
        return env
    if credential_store is None:
        raise MCPAuthError("credential store is not configured")

    ref = AuthRef(kind=config.auth.ref_kind, ref=config.auth.credential_id)
    value = await credential_store.resolve(ref, scope_context={"agent_id": agent_id})
    if value is None:
        raise MCPAuthError(f"credential not found: {config.auth.credential_id}")

    formatted = config.auth.format.replace("{value}", value)
    injection = (config.auth.injection or "").strip()
    if injection.startswith("env:"):
        _, var_name = injection.split(":", 1)
        var_name = var_name.strip()
        if not var_name:
            raise MCPAuthError(f"invalid auth env injection target: {injection}")
        env[var_name] = formatted
    else:
        env[default_var] = formatted
    return env


def build_mcp_credential_resolver(
    *,
    backend: str,
    file_root: str,
    environ: dict[str, str] | None = None,
) -> CredentialResolver | None:
    """Builds one credential resolver instance for MCP auth use."""
    from anyagent.config.schema import CredentialsConfig, CredentialsFileConfig
    from anyagent.server.security.credential_runtime import build_credential_store

    mode = (backend or "").strip().lower()
    if mode in {"", "none"}:
        return None
    if mode not in {"env", "file"}:
        raise MCPAuthError(f"unsupported MCP credential backend: {backend}")
    config = CredentialsConfig(
        backend=mode,  # type: ignore[arg-type]
        writable=False,
        file=CredentialsFileConfig(root=file_root or ".anyagent/credentials"),
    )
    return build_credential_store(config, environ=environ)


def _read_credential_value(path: Path, kind: str) -> str | None:
    """Reads one credential value from Tool Runtime credential file format."""
    try:
        raw = path.read_text("utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return None

    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") != kind:
        return None
    value = obj.get("value")
    if isinstance(value, str) and value:
        return value
    return None
