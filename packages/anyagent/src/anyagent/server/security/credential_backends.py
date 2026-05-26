from __future__ import annotations

import asyncio
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef


_CREDENTIAL_ID_RE = re.compile(r"^[a-z0-9_]+$")


class ReadOnlyCredentialStoreError(RuntimeError):
    """Raised when a credential backend does not support mutation."""


class CredentialStore(ABC):
    """Defines write-only credential storage with internal-only resolve."""

    @abstractmethod
    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Writes or updates one credential without exposing plaintext in list APIs."""

    @abstractmethod
    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        """Resolves a credential plaintext value for server-side tool execution."""

    @abstractmethod
    async def delete(self, credential_id: str) -> bool:
        """Deletes all entries under credential_id and returns whether anything changed."""

    @abstractmethod
    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        """Lists credential references without plaintext values."""


@dataclass(frozen=True, slots=True)
class _CredentialEntry:
    kind: str
    value: str
    scope: CredentialScope
    metadata: dict[str, Any]


class EnvBackend(CredentialStore):
    """Resolves credentials from env vars with an in-memory write fallback."""

    def __init__(self, *, environ: dict[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        self._lock = asyncio.Lock()
        self._entries: dict[str, dict[str, dict[str, _CredentialEntry]]] = {}

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")

        entry = _CredentialEntry(kind=kind, value=value, scope=scope, metadata=dict(metadata or {}))
        async with self._lock:
            by_kind = self._entries.setdefault(credential_id, {})
            by_scope = by_kind.setdefault(kind, {})
            by_scope[_scope_key(scope)] = entry

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = None
        if isinstance(scope_context, dict):
            agent_id = scope_context.get("agent_id")

        candidates = await self._get_candidates(credential_id=credential_id, kind=kind, agent_id=agent_id)
        for entry in candidates:
            env_var_name = entry.metadata.get("env_var_name")
            if isinstance(env_var_name, str) and env_var_name:
                value = self._environ.get(env_var_name)
                if value:
                    return value

        default_var = f"CREDENTIAL__{credential_id.upper()}"
        value = self._environ.get(default_var)
        if value:
            return value

        for entry in candidates:
            if entry.value:
                return entry.value
        return None

    async def delete(self, credential_id: str) -> bool:
        _validate_credential_id(credential_id)
        async with self._lock:
            existed = credential_id in self._entries
            self._entries.pop(credential_id, None)
            return existed

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async with self._lock:
            for credential_id, by_kind in self._entries.items():
                for kind, by_scope in by_kind.items():
                    for entry in by_scope.values():
                        if scope is not None and not _scope_matches(filter_scope=scope, entry_scope=entry.scope):
                            continue
                        out.append(
                            {
                                "credential_id": credential_id,
                                "kind": kind,
                                "scope": entry.scope.model_dump(exclude_none=True),
                                "metadata": dict(entry.metadata),
                            }
                        )
        return out

    async def _get_candidates(self, *, credential_id: str, kind: str, agent_id: Any) -> list[_CredentialEntry]:
        async with self._lock:
            by_scope = self._entries.get(credential_id, {}).get(kind, {})
            candidates: list[_CredentialEntry | None] = []
            if isinstance(agent_id, str) and agent_id.strip():
                candidates.append(by_scope.get(f"agent:{agent_id.strip()}"))
            candidates.append(by_scope.get("global"))
            return [candidate for candidate in candidates if candidate is not None]


@dataclass(frozen=True, slots=True)
class _FileCredential:
    credential_id: str
    kind: str
    value: str
    scope: CredentialScope
    metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None


class FileBackend(CredentialStore):
    """Stores credentials on filesystem with chmod 600 and atomic writes."""

    def __init__(self, *, root: str | Path, environ: dict[str, str] | None = None) -> None:
        self._root = Path(root)
        self._environ = os.environ if environ is None else environ

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")

        now = datetime.now(timezone.utc).isoformat()
        path = self._path_for(scope=scope, credential_id=credential_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_credential_file(path)
        payload = {
            "credential_id": credential_id,
            "kind": kind,
            "value": value,
            "scope": scope.model_dump(exclude_none=True),
            "metadata": dict(metadata or {}),
            "created_at": existing.created_at if existing is not None else now,
            "updated_at": now,
        }
        _atomic_write_json(path, payload)

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = scope_context.get("agent_id") if isinstance(scope_context, dict) else None
        if isinstance(agent_id, str) and agent_id.strip():
            agent_path = self._path_for(scope=CredentialScope(level="agent", agent_id=agent_id.strip()), credential_id=credential_id)
            entry = _read_credential_file(agent_path)
            if entry is not None and entry.kind == kind:
                return entry.value

        global_path = self._path_for(scope=CredentialScope(level="global"), credential_id=credential_id)
        entry = _read_credential_file(global_path)
        if entry is not None and entry.kind == kind:
            return entry.value

        env_var = f"CREDENTIAL__{credential_id.upper()}"
        value = self._environ.get(env_var)
        if value:
            return value
        return None

    async def delete(self, credential_id: str) -> bool:
        _validate_credential_id(credential_id)
        deleted_any = False
        global_path = self._path_for(scope=CredentialScope(level="global"), credential_id=credential_id)
        if global_path.exists():
            global_path.unlink()
            deleted_any = True

        agents_root = self._root / "agents"
        if agents_root.exists():
            for path in agents_root.glob(f"*/{credential_id}.json"):
                try:
                    path.unlink()
                    deleted_any = True
                except FileNotFoundError:
                    pass
        return deleted_any

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self._root.exists():
            return out

        candidates: list[Path] = []
        candidates.extend((self._root / "global").glob("*.json"))
        agents_root = self._root / "agents"
        if agents_root.exists():
            candidates.extend(agents_root.glob("*/*.json"))

        for path in candidates:
            entry = _read_credential_file(path)
            if entry is None:
                continue
            if scope is not None and not _scope_matches(filter_scope=scope, entry_scope=entry.scope):
                continue
            out.append(
                {
                    "credential_id": entry.credential_id,
                    "kind": entry.kind,
                    "scope": entry.scope.model_dump(exclude_none=True),
                    "metadata": dict(entry.metadata),
                }
            )
        return out

    def _path_for(self, *, scope: CredentialScope, credential_id: str) -> Path:
        if scope.level == "global":
            return self._root / "global" / f"{credential_id}.json"
        if scope.level == "agent":
            if not scope.agent_id:
                raise ValueError("scope.agent_id is required for agent scope")
            return self._root / "agents" / scope.agent_id / f"{credential_id}.json"
        raise ValueError(f"unsupported scope level: {scope.level}")


@dataclass(frozen=True, slots=True)
class InfisicalBackendConfig:
    host: str
    client_id: str
    client_secret: str
    project_id: str
    environment: str
    credential_root_path: str
    path_layout: str = "scoped"
    cache_ttl_seconds: int = 60


class InfisicalBackend(CredentialStore):
    """Read-only Infisical credential backend for Tool Runtime credential stores."""

    def __init__(
        self,
        *,
        config: InfisicalBackendConfig,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        try:
            factory = client_factory or _load_infisical_sdk_client()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("infisical credential backend requires installing anyagent[infisical]") from exc

        self._config = config
        self._client = factory(host=config.host, cache_ttl=config.cache_ttl_seconds)
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        raise ReadOnlyCredentialStoreError("infisical backend is read-only; manage secrets in Infisical")

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = ""
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()

        await self._ensure_login()
        if self._is_flat_layout():
            candidate_paths = [self._normalized_root_path()]
        else:
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
                raise

            value = getattr(secret, "secretValue", None)
            if isinstance(value, str) and value:
                return value
        return None

    async def delete(self, credential_id: str) -> bool:
        _validate_credential_id(credential_id)
        raise ReadOnlyCredentialStoreError("infisical backend is read-only; manage secrets in Infisical")

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        await self._ensure_login()
        response = await asyncio.to_thread(
            self._client.secrets.list_secrets,
            self._config.environment,
            self._normalized_root_path(),
            project_id=self._config.project_id,
            recursive=True,
            include_imports=False,
            expand_secret_references=False,
            view_secret_value=False,
        )

        out: list[dict[str, Any]] = []
        for secret in list(getattr(response, "secrets", []) or []):
            secret_key = getattr(secret, "secretKey", None)
            secret_path = getattr(secret, "secretPath", None)
            if not isinstance(secret_key, str) or not isinstance(secret_path, str):
                continue

            if self._is_flat_layout():
                parsed_scope, kind = CredentialScope(level="global"), "secret"
            else:
                parsed_scope, kind = self._parse_scope_and_kind(secret_path)
            if parsed_scope is None or kind is None:
                continue
            if scope is not None and not _scope_matches(filter_scope=scope, entry_scope=parsed_scope):
                continue
            out.append(
                {
                    "credential_id": secret_key,
                    "kind": kind,
                    "scope": parsed_scope.model_dump(exclude_none=True),
                    "metadata": {
                        "provider": "infisical",
                        "secret_path": secret_path,
                        "environment": self._config.environment,
                        "project_id": self._config.project_id,
                    },
                }
            )
        return out

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if self._logged_in:
                return
            await asyncio.to_thread(
                self._client.auth.universal_auth.login,
                self._config.client_id,
                self._config.client_secret,
            )
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

    def _parse_scope_and_kind(self, secret_path: str) -> tuple[CredentialScope | None, str | None]:
        root = self._normalized_root_path().rstrip("/")
        normalized_path = secret_path.rstrip("/")
        if normalized_path == root:
            relative = ""
        elif normalized_path.startswith(f"{root}/"):
            relative = normalized_path[len(root) + 1 :]
        else:
            return None, None

        parts = [part for part in relative.split("/") if part]
        if len(parts) == 2 and parts[0] == "global":
            return CredentialScope(level="global"), parts[1]
        if len(parts) == 3 and parts[0] == "agents":
            return CredentialScope(level="agent", agent_id=parts[1]), parts[2]
        return None, None

    def _is_flat_layout(self) -> bool:
        return (self._config.path_layout or "").strip().lower() == "flat"


def _validate_credential_id(credential_id: str) -> None:
    if not credential_id:
        raise ValueError("credential_id must be non-empty")
    if not _CREDENTIAL_ID_RE.fullmatch(credential_id):
        raise ValueError("credential_id must match ^[a-z0-9_]+$")


def _scope_key(scope: CredentialScope) -> str:
    if scope.level == "global":
        return "global"
    return f"agent:{scope.agent_id}"


def _scope_matches(*, filter_scope: CredentialScope, entry_scope: CredentialScope) -> bool:
    if filter_scope.level == "global":
        return entry_scope.level == "global"
    if filter_scope.level == "agent":
        return entry_scope.level == "agent" and entry_scope.agent_id == filter_scope.agent_id
    return False


def _looks_like_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return "404" in text or "not found" in text


def _load_infisical_sdk_client() -> Callable[..., Any]:
    from infisical_sdk import InfisicalSDKClient

    return InfisicalSDKClient


def _read_credential_file(path: Path) -> _FileCredential | None:
    try:
        raw = path.read_text("utf-8")
    except FileNotFoundError:
        return None

    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    credential_id = obj.get("credential_id")
    kind = obj.get("kind")
    value = obj.get("value")
    scope_obj = obj.get("scope")
    metadata = obj.get("metadata") or {}
    if not isinstance(credential_id, str) or not isinstance(kind, str) or not isinstance(value, str):
        return None
    if not isinstance(scope_obj, dict):
        return None
    if not isinstance(metadata, dict):
        metadata = {}

    try:
        scope = CredentialScope.model_validate(scope_obj)
    except Exception:
        return None

    created_at = obj.get("created_at")
    updated_at = obj.get("updated_at")
    if created_at is not None and not isinstance(created_at, str):
        created_at = None
    if updated_at is not None and not isinstance(updated_at, str):
        updated_at = None
    return _FileCredential(
        credential_id=credential_id,
        kind=kind,
        value=value,
        scope=scope,
        metadata=dict(metadata),
        created_at=created_at,
        updated_at=updated_at,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
