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
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
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
    expires_at: datetime | None = None
    rotate_before: datetime | None = None


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
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")

        _validate_lifecycle(expires_at=expires_at, rotate_before=rotate_before)
        entry = _CredentialEntry(
            kind=kind,
            value=value,
            scope=scope,
            metadata=dict(metadata or {}),
            expires_at=expires_at,
            rotate_before=rotate_before,
        )
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
        session_key = None
        if isinstance(scope_context, dict):
            agent_id = scope_context.get("agent_id")
            session_key = scope_context.get("session_key")

        candidates = await self._get_candidates(credential_id=credential_id, kind=kind, agent_id=agent_id, session_key=session_key)
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
                                **_lifecycle_ref_fields(expires_at=entry.expires_at, rotate_before=entry.rotate_before),
                            }
                        )
        return out

    async def _get_candidates(self, *, credential_id: str, kind: str, agent_id: Any, session_key: Any) -> list[_CredentialEntry]:
        async with self._lock:
            by_scope = self._entries.get(credential_id, {}).get(kind, {})
            candidates: list[_CredentialEntry | None] = []
            if isinstance(agent_id, str) and agent_id.strip() and isinstance(session_key, str) and session_key.strip():
                candidates.append(by_scope.get(f"session:{agent_id.strip()}:{session_key.strip()}"))
            if isinstance(agent_id, str) and agent_id.strip():
                candidates.append(by_scope.get(f"agent:{agent_id.strip()}"))
            candidates.append(by_scope.get("global"))
            return [candidate for candidate in candidates if candidate is not None and not _is_expired(candidate.expires_at)]


@dataclass(frozen=True, slots=True)
class _FileCredential:
    credential_id: str
    kind: str
    value: str
    scope: CredentialScope
    metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None
    expires_at: datetime | None
    rotate_before: datetime | None


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
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")

        _validate_lifecycle(expires_at=expires_at, rotate_before=rotate_before)
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
            "expires_at": _datetime_to_json(expires_at),
            "rotate_before": _datetime_to_json(rotate_before),
        }
        _atomic_write_json(path, payload)

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = scope_context.get("agent_id") if isinstance(scope_context, dict) else None
        session_key = scope_context.get("session_key") if isinstance(scope_context, dict) else None
        if isinstance(agent_id, str) and agent_id.strip() and isinstance(session_key, str) and session_key.strip():
            session_path = self._path_for(
                scope=CredentialScope(level="session", agent_id=agent_id.strip(), session_key=session_key.strip()),
                credential_id=credential_id,
            )
            entry = _read_credential_file(session_path)
            if entry is not None and entry.kind == kind and not _is_expired(entry.expires_at):
                return entry.value
        if isinstance(agent_id, str) and agent_id.strip():
            agent_path = self._path_for(scope=CredentialScope(level="agent", agent_id=agent_id.strip()), credential_id=credential_id)
            entry = _read_credential_file(agent_path)
            if entry is not None and entry.kind == kind and not _is_expired(entry.expires_at):
                return entry.value

        global_path = self._path_for(scope=CredentialScope(level="global"), credential_id=credential_id)
        entry = _read_credential_file(global_path)
        if entry is not None and entry.kind == kind and not _is_expired(entry.expires_at):
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
        sessions_root = self._root / "sessions"
        if sessions_root.exists():
            for path in sessions_root.glob(f"*/*/{credential_id}.json"):
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
        sessions_root = self._root / "sessions"
        if sessions_root.exists():
            candidates.extend(sessions_root.glob("*/*/*.json"))

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
                    **_lifecycle_ref_fields(expires_at=entry.expires_at, rotate_before=entry.rotate_before),
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
        if scope.level == "session":
            if not scope.agent_id or not scope.session_key:
                raise ValueError("scope.agent_id and scope.session_key are required for session scope")
            return self._root / "sessions" / scope.agent_id / scope.session_key / f"{credential_id}.json"
        raise ValueError(f"unsupported scope level: {scope.level}")


@dataclass(frozen=True, slots=True)
class DatabaseBackendConfig:
    postgres_dsn: str
    encryption_key: str
    schema_name: str = "public"
    create_schema: bool = False


class DatabaseBackend(CredentialStore):
    """PostgreSQL credential store using pgcrypto encrypted secret columns."""

    def __init__(self, *, config: DatabaseBackendConfig, engine: Any | None = None) -> None:
        if not config.postgres_dsn:
            raise RuntimeError("db credential backend requires POSTGRES_DSN or CREDENTIAL_POSTGRES_DSN")
        if not config.encryption_key:
            raise RuntimeError("db credential backend requires CREDENTIAL_ENCRYPTION_KEY")
        self._config = config
        self._engine = engine or _create_postgres_engine(config.postgres_dsn)
        self._ready = False
        self._ready_lock = asyncio.Lock()

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")
        _validate_lifecycle(expires_at=expires_at, rotate_before=rotate_before)
        await self._ensure_ready()
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {_qualified(self._config.schema_name, "credentials")}
                      (credential_id, kind, scope_level, agent_id, session_key, value_ciphertext, metadata_json, expires_at, rotate_before, updated_at)
                    VALUES
                      (:credential_id, :kind, :scope_level, :agent_id, :session_key,
                       pgp_sym_encrypt(:value, :encryption_key), CAST(:metadata_json AS jsonb), :expires_at, :rotate_before, now())
                    ON CONFLICT (credential_id, kind, scope_level, agent_id_norm, session_key_norm)
                    DO UPDATE SET value_ciphertext=EXCLUDED.value_ciphertext,
                                  metadata_json=EXCLUDED.metadata_json,
                                  expires_at=EXCLUDED.expires_at,
                                  rotate_before=EXCLUDED.rotate_before,
                                  updated_at=now()
                    """
                ),
                {
                    "credential_id": credential_id,
                    "kind": kind.strip(),
                    "scope_level": scope.level,
                    "agent_id": scope.agent_id,
                    "session_key": scope.session_key,
                    "value": value,
                    "encryption_key": self._config.encryption_key,
                    "metadata_json": json.dumps(dict(metadata or {}), separators=(",", ":")),
                    "expires_at": expires_at,
                    "rotate_before": rotate_before,
                },
            )

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None
        await self._ensure_ready()
        agent_id = scope_context.get("agent_id") if isinstance(scope_context, dict) else None
        session_key = scope_context.get("session_key") if isinstance(scope_context, dict) else None
        candidates: list[tuple[str, str | None, str | None]] = []
        if isinstance(agent_id, str) and agent_id.strip() and isinstance(session_key, str) and session_key.strip():
            candidates.append(("session", agent_id.strip(), session_key.strip()))
        if isinstance(agent_id, str) and agent_id.strip():
            candidates.append(("agent", agent_id.strip(), None))
        candidates.append(("global", None, None))
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            for scope_level, scoped_agent_id, scoped_session_key in candidates:
                row = (
                    await conn.execute(
                        text(
                            f"""
                            SELECT pgp_sym_decrypt(value_ciphertext, :encryption_key) AS value
                            FROM {_qualified(self._config.schema_name, "credentials")}
                            WHERE credential_id=:credential_id
                              AND kind=:kind
                              AND scope_level=:scope_level
                              AND agent_id_norm=COALESCE(:agent_id, '')
                              AND session_key_norm=COALESCE(:session_key, '')
                              AND (expires_at IS NULL OR expires_at > now())
                            LIMIT 1
                            """
                        ),
                        {
                            "credential_id": credential_id,
                            "kind": kind,
                            "scope_level": scope_level,
                            "agent_id": scoped_agent_id,
                            "session_key": scoped_session_key,
                            "encryption_key": self._config.encryption_key,
                        },
                    )
                ).mappings().first()
                if row is not None and isinstance(row.get("value"), str):
                    return row["value"]
        return None

    async def delete(self, credential_id: str) -> bool:
        _validate_credential_id(credential_id)
        await self._ensure_ready()
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"DELETE FROM {_qualified(self._config.schema_name, 'credentials')} WHERE credential_id=:credential_id"),
                {"credential_id": credential_id},
            )
        return int(result.rowcount or 0) > 0

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        await self._ensure_ready()
        from sqlalchemy import text

        where = ""
        params: dict[str, Any] = {}
        if scope is not None:
            where = "WHERE scope_level=:scope_level AND agent_id_norm=COALESCE(:agent_id, '') AND session_key_norm=COALESCE(:session_key, '')"
            params = {"scope_level": scope.level, "agent_id": scope.agent_id, "session_key": scope.session_key}
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"""
                        SELECT credential_id, kind, scope_level, agent_id, session_key, metadata_json, expires_at, rotate_before
                        FROM {_qualified(self._config.schema_name, "credentials")}
                        {where}
                        ORDER BY credential_id, kind, scope_level, agent_id_norm, session_key_norm
                        """
                    ),
                    params,
                )
            ).mappings().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            row_scope = CredentialScope(
                level=row["scope_level"],
                agent_id=row.get("agent_id"),
                session_key=row.get("session_key"),
            )
            out.append(
                {
                    "credential_id": row["credential_id"],
                    "kind": row["kind"],
                    "scope": row_scope.model_dump(exclude_none=True),
                    "metadata": dict(row.get("metadata_json") or {}),
                    **_lifecycle_ref_fields(expires_at=row.get("expires_at"), rotate_before=row.get("rotate_before")),
                }
            )
        return out

    async def record_audit(self, payload: dict[str, Any]) -> None:
        await self._ensure_ready()
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {_qualified(self._config.schema_name, "credential_audit")}
                      (audit_ref, operation, credential_id, kind, scope_level, agent_id, session_key, deleted, payload_json)
                    VALUES
                      (:audit_ref, :operation, :credential_id, :kind, :scope_level, :agent_id, :session_key, :deleted, CAST(:payload_json AS jsonb))
                    """
                ),
                {
                    "audit_ref": payload.get("audit_ref"),
                    "operation": payload.get("operation"),
                    "credential_id": payload.get("credential_id"),
                    "kind": payload.get("kind"),
                    "scope_level": payload.get("scope_level"),
                    "agent_id": payload.get("agent_id"),
                    "session_key": payload.get("session_key"),
                    "deleted": payload.get("deleted"),
                    "payload_json": json.dumps(payload, separators=(",", ":")),
                },
            )

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            from sqlalchemy import text

            if self._config.create_schema:
                statements = [_postgres_credentials_create_sql(self._config.schema_name), _postgres_credential_audit_create_sql(self._config.schema_name)]
                async with self._engine.begin() as conn:
                    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{_validate_identifier(self._config.schema_name)}"'))
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
                    for statement in statements:
                        await conn.execute(text(statement))
            self._ready = True


@dataclass(frozen=True, slots=True)
class VaultBackendConfig:
    base_url: str
    token: str
    mount: str = "secret"
    root_path: str = "anyagent/credentials"
    timeout_s: float = 10.0


class VaultBackend(CredentialStore):
    """HashiCorp Vault KV v2 credential store."""

    def __init__(self, *, config: VaultBackendConfig, client: Any | None = None) -> None:
        if not config.base_url or not config.token:
            raise RuntimeError("vault credential backend requires VAULT_ADDR and VAULT_TOKEN")
        self._config = config
        self._client = client
        self._known_refs: set[tuple[str, str, str, str | None, str | None]] = set()

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
    ) -> None:
        _validate_credential_id(credential_id)
        if not kind.strip():
            raise ValueError("kind must be non-empty")
        if value == "":
            raise ValueError("value must be non-empty")
        _validate_lifecycle(expires_at=expires_at, rotate_before=rotate_before)
        await self._request(
            "POST",
            self._data_url(scope=scope, kind=kind, credential_id=credential_id),
            json_payload={
                "data": {
                    "kind": kind,
                    "value": value,
                    "scope": scope.model_dump(exclude_none=True),
                    "metadata": dict(metadata or {}),
                    "expires_at": _datetime_to_json(expires_at),
                    "rotate_before": _datetime_to_json(rotate_before),
                }
            },
        )
        self._known_refs.add((credential_id, kind.strip(), scope.level, scope.agent_id, scope.session_key))

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None
        agent_id = scope_context.get("agent_id") if isinstance(scope_context, dict) else None
        session_key = scope_context.get("session_key") if isinstance(scope_context, dict) else None
        scopes: list[CredentialScope] = []
        if isinstance(agent_id, str) and agent_id.strip() and isinstance(session_key, str) and session_key.strip():
            scopes.append(CredentialScope(level="session", agent_id=agent_id.strip(), session_key=session_key.strip()))
        if isinstance(agent_id, str) and agent_id.strip():
            scopes.append(CredentialScope(level="agent", agent_id=agent_id.strip()))
        scopes.append(CredentialScope(level="global"))
        for scope in scopes:
            payload = await self._read_secret(scope=scope, kind=kind, credential_id=credential_id)
            if not payload:
                continue
            if payload.get("kind") != kind:
                continue
            if _is_expired(_parse_datetime(payload.get("expires_at"))):
                continue
            value = payload.get("value")
            if isinstance(value, str) and value:
                return value
        return None

    async def delete(self, credential_id: str) -> bool:
        _validate_credential_id(credential_id)
        deleted = False
        refs = await self.list_refs()
        for ref in refs:
            if ref.get("credential_id") != credential_id:
                continue
            scope = CredentialScope.model_validate(ref.get("scope"))
            await self._request("DELETE", self._data_url(scope=scope, kind=str(ref.get("kind")), credential_id=credential_id))
            self._known_refs.discard((credential_id, str(ref.get("kind")), scope.level, scope.agent_id, scope.session_key))
            deleted = True
        return deleted

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._known_refs:
            candidates = sorted(self._known_refs)
            for credential_id, kind, scope_level, agent_id, session_key in candidates:
                candidate_scope = CredentialScope(level=scope_level, agent_id=agent_id, session_key=session_key)
                if scope is not None and not _scope_matches(filter_scope=scope, entry_scope=candidate_scope):
                    continue
                payload = await self._read_secret(scope=candidate_scope, kind=kind, credential_id=credential_id)
                if payload is not None:
                    out.append(_vault_ref(credential_id=credential_id, kind=kind, scope=candidate_scope, payload=payload))
            return out

        # KV v2 has no efficient recursive list. Without process-local refs,
        # global refs remain discoverable through the stable layout prefix.
        candidate_scope = scope or CredentialScope(level="global")
        prefix = self._scope_path(candidate_scope)
        for kind in await self._list_keys(f"{prefix}/"):
            for credential_id in await self._list_keys(f"{prefix}/{kind}/"):
                payload = await self._read_secret(scope=candidate_scope, kind=kind, credential_id=credential_id)
                if payload is not None:
                    out.append(_vault_ref(credential_id=credential_id, kind=kind, scope=candidate_scope, payload=payload))
        return out

    async def _read_secret(self, *, scope: CredentialScope, kind: str, credential_id: str) -> dict[str, Any] | None:
        response = await self._request("GET", self._data_url(scope=scope, kind=kind, credential_id=credential_id), allow_not_found=True)
        if response is None:
            return None
        data = response.get("data", {}).get("data")
        return data if isinstance(data, dict) else None

    async def _list_keys(self, path: str) -> list[str]:
        response = await self._request("LIST", self._metadata_url(path=path), allow_not_found=True)
        if response is None:
            return []
        keys = response.get("data", {}).get("keys", [])
        return [str(key).rstrip("/") for key in keys if isinstance(key, str)]

    async def _request(self, method: str, url: str, *, json_payload: dict[str, Any] | None = None, allow_not_found: bool = False) -> dict[str, Any] | None:
        import httpx

        headers = {"X-Vault-Token": self._config.token}
        client = self._client
        if client is not None:
            response = await client.request(method, url, headers=headers, json=json_payload)
        else:
            async with httpx.AsyncClient(timeout=self._config.timeout_s) as http:
                response = await http.request(method, url, headers=headers, json=json_payload)
        if response.status_code == 404 and allow_not_found:
            return None
        response.raise_for_status()
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _data_url(self, *, scope: CredentialScope, kind: str, credential_id: str) -> str:
        path = f"{self._scope_path(scope)}/{kind.strip()}/{credential_id}"
        return f"{self._base_url()}/v1/{self._mount()}/data/{path}"

    def _metadata_url(self, *, path: str) -> str:
        return f"{self._base_url()}/v1/{self._mount()}/metadata/{path.strip('/')}"

    def _scope_path(self, scope: CredentialScope) -> str:
        root = self._root_path()
        if scope.level == "global":
            return f"{root}/global"
        if scope.level == "agent":
            return f"{root}/agents/{scope.agent_id}"
        return f"{root}/sessions/{scope.agent_id}/{scope.session_key}"

    def _base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    def _mount(self) -> str:
        return self._config.mount.strip("/")

    def _root_path(self) -> str:
        return self._config.root_path.strip("/")


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
    token: str | None = None


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
        self._client = factory(host=config.host, cache_ttl=config.cache_ttl_seconds, token=config.token)
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        rotate_before: datetime | None = None,
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
        session_key = ""
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()
        if isinstance(scope_context, dict) and isinstance(scope_context.get("session_key"), str):
            session_key = scope_context["session_key"].strip()

        await self._ensure_login()
        if self._is_flat_layout():
            candidate_paths = [self._normalized_root_path()]
        else:
            candidate_paths = []
            if agent_id and session_key:
                candidate_paths.append(self._session_path(agent_id=agent_id, session_key=session_key, kind=kind))
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
        # Service Token already applied during client construction.
        if self._config.token:
            self._logged_in = True
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

    def _session_path(self, *, agent_id: str, session_key: str, kind: str) -> str:
        return f"{self._normalized_root_path()}/sessions/{agent_id.strip()}/{session_key.strip()}/{kind.strip()}"

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
        if len(parts) == 4 and parts[0] == "sessions":
            return CredentialScope(level="session", agent_id=parts[1], session_key=parts[2]), parts[3]
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
    if scope.level == "session":
        return f"session:{scope.agent_id}:{scope.session_key}"
    return f"agent:{scope.agent_id}"


def _scope_matches(*, filter_scope: CredentialScope, entry_scope: CredentialScope) -> bool:
    if filter_scope.level == "global":
        return entry_scope.level == "global"
    if filter_scope.level == "agent":
        return entry_scope.level == "agent" and entry_scope.agent_id == filter_scope.agent_id
    if filter_scope.level == "session":
        return (
            entry_scope.level == "session"
            and entry_scope.agent_id == filter_scope.agent_id
            and entry_scope.session_key == filter_scope.session_key
        )
    return False


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _validate_lifecycle(*, expires_at: datetime | None, rotate_before: datetime | None) -> None:
    if expires_at is not None and rotate_before is not None and rotate_before > expires_at:
        raise ValueError("rotate_before must be before or equal to expires_at")


def _vault_ref(*, credential_id: str, kind: str, scope: CredentialScope, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "credential_id": credential_id,
        "kind": kind,
        "scope": scope.model_dump(exclude_none=True),
        "metadata": dict(payload.get("metadata") or {}),
        **_lifecycle_ref_fields(
            expires_at=_parse_datetime(payload.get("expires_at")),
            rotate_before=_parse_datetime(payload.get("rotate_before")),
        ),
    }


def _lifecycle_ref_fields(*, expires_at: datetime | None, rotate_before: datetime | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if expires_at is not None:
        out["expires_at"] = _datetime_to_json(expires_at) or ""
    if rotate_before is not None:
        out["rotate_before"] = _datetime_to_json(rotate_before) or ""
    return out


def _create_postgres_engine(postgres_dsn: str) -> Any:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("db credential backend requires installing anyagent[postgres]") from exc

    dsn = postgres_dsn
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://") :]
    return create_async_engine(dsn, pool_pre_ping=True, future=True)


def _validate_identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", value):
        raise ValueError("invalid SQL identifier")
    return value


def _qualified(schema: str, table: str) -> str:
    return f'"{_validate_identifier(schema)}"."{_validate_identifier(table)}"'


def _postgres_credentials_create_sql(schema_name: str) -> str:
    table = _qualified(schema_name, "credentials")
    return f"""
    CREATE TABLE IF NOT EXISTS {table} (
      credential_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      scope_level TEXT NOT NULL CHECK (scope_level IN ('global', 'agent', 'session')),
      agent_id TEXT NULL,
      session_key TEXT NULL,
      agent_id_norm TEXT GENERATED ALWAYS AS (COALESCE(agent_id, '')) STORED,
      session_key_norm TEXT GENERATED ALWAYS AS (COALESCE(session_key, '')) STORED,
      value_ciphertext BYTEA NOT NULL,
      metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      expires_at TIMESTAMPTZ NULL,
      rotate_before TIMESTAMPTZ NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (credential_id, kind, scope_level, agent_id_norm, session_key_norm)
    )
    """


def _postgres_credential_audit_create_sql(schema_name: str) -> str:
    table = _qualified(schema_name, "credential_audit")
    return f"""
    CREATE TABLE IF NOT EXISTS {table} (
      audit_ref TEXT PRIMARY KEY,
      operation TEXT NOT NULL,
      credential_id TEXT NOT NULL,
      kind TEXT NULL,
      scope_level TEXT NULL,
      agent_id TEXT NULL,
      session_key TEXT NULL,
      deleted BOOLEAN NULL,
      payload_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """


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
        expires_at=_parse_datetime(obj.get("expires_at")),
        rotate_before=_parse_datetime(obj.get("rotate_before")),
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
