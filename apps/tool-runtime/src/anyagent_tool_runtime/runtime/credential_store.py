from __future__ import annotations

import asyncio
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from anyagent.protocol.tool_runtime import AuthRef
from anyagent.protocol.credential_vault import CredentialScope


_CREDENTIAL_ID_RE = re.compile(r"^[a-z0-9_]+$")

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
        """Writes or updates a credential in an idempotent way."""

    @abstractmethod
    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        """Resolves a credential plaintext value for Tool Runtime internal use only."""

    @abstractmethod
    async def delete(self, credential_id: str) -> bool:
        """Deletes all entries under credential_id and returns whether anything changed."""

    @abstractmethod
    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        """Lists credential references without returning plaintext values."""


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
        # credential_id -> kind -> scope_key -> entry
        self._entries: dict[str, dict[str, dict[str, _CredentialEntry]]] = {}

    async def set(
        self,
        credential_id: str,
        kind: str,
        value: str,
        scope: CredentialScope,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stores credentials in memory so EnvBackend can be used without persistence."""

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
        """Resolves the value by env var first, then default env var, then in-memory entry."""

        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = None
        if scope_context is not None:
            agent_id = scope_context.get("agent_id")

        candidates = await self._get_candidates(credential_id=credential_id, kind=kind, agent_id=agent_id)

        # 1) metadata.env_var_name for scoped entries (agent first, then global)
        for entry in candidates:
            env_var_name = entry.metadata.get("env_var_name")
            if isinstance(env_var_name, str) and env_var_name:
                v = self._environ.get(env_var_name)
                if v:
                    return v

        # 2) fallback name based on credential_id
        default_var = f"CREDENTIAL__{credential_id.upper()}"
        v = self._environ.get(default_var)
        if v:
            return v

        # 3) in-memory fallback
        for entry in candidates:
            if entry.value:
                return entry.value
        return None

    async def delete(self, credential_id: str) -> bool:
        """Deletes all stored in-memory values; environment variables cannot be deleted."""

        _validate_credential_id(credential_id)
        async with self._lock:
            existed = credential_id in self._entries
            self._entries.pop(credential_id, None)
            return existed

    async def list_refs(self, scope: CredentialScope | None = None) -> list[dict[str, Any]]:
        """Lists in-memory references; env-only credentials are not enumerable."""

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
                                "scope": entry.scope.model_dump(),
                                "metadata": dict(entry.metadata),
                            }
                        )
        return out

    async def _get_candidates(self, *, credential_id: str, kind: str, agent_id: str | None) -> list[_CredentialEntry]:
        async with self._lock:
            by_kind = self._entries.get(credential_id, {}).get(kind, {})
            candidates: list[_CredentialEntry] = []
            if agent_id:
                candidates.append(by_kind.get(f"agent:{agent_id}"))
            candidates.append(by_kind.get("global"))
            return [c for c in candidates if c is not None]


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
