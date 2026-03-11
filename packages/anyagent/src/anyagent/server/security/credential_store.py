from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from anyagent.mcp.auth import CredentialResolver
from anyagent.protocol.credential_vault import (
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)
from anyagent.protocol.tool_runtime import AuthRef

logger = logging.getLogger("anyagent.credentials")


def _build_credential_audit_ref(*, operation: str, credential_id: str) -> str:
    raw = f"{operation}:{credential_id}:{time.time_ns()}".encode("utf-8", errors="replace")
    return f"cred_aud_{hashlib.sha256(raw).hexdigest()[:24]}"


def _log_credential_audit(
    *,
    operation: str,
    credential_id: str,
    kind: str | None = None,
    scope_level: str | None = None,
    agent_id: str | None = None,
    deleted: bool | None = None,
) -> None:
    payload = {
        "audit_ref": _build_credential_audit_ref(operation=operation, credential_id=credential_id),
        "operation": operation,
        "credential_id": credential_id,
        "kind": kind,
        "scope_level": scope_level,
        "agent_id": agent_id,
        "deleted": deleted,
    }
    logger.info("credential_audit %s", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class InMemoryCredentialStore(CredentialResolver):
    def __init__(self) -> None:
        self._refs: dict[str, AdminCredentialRef] = {}
        self._values: dict[tuple[str, str, str | None], str] = {}

    @staticmethod
    def _key(*, credential_id: str, scope_level: str, agent_id: str | None) -> tuple[str, str, str | None]:
        return credential_id.strip(), scope_level.strip(), agent_id.strip() if isinstance(agent_id, str) else None

    async def set(self, req: AdminCredentialSetRequest) -> AdminCredentialRef:
        ref = AdminCredentialRef(
            credential_id=req.credential_id,
            kind=req.kind,
            scope=req.scope,
            metadata=dict(req.metadata or {}),
        )
        key = self._key(
            credential_id=req.credential_id,
            scope_level=req.scope.level,
            agent_id=req.scope.agent_id,
        )
        self._refs[req.credential_id] = ref
        self._values[key] = req.value
        _log_credential_audit(
            operation="set",
            credential_id=req.credential_id,
            kind=req.kind,
            scope_level=req.scope.level,
            agent_id=req.scope.agent_id,
        )
        return ref

    async def list(self) -> AdminCredentialListResponse:
        refs = [self._refs[k] for k in sorted(self._refs.keys())]
        return AdminCredentialListResponse(credentials=refs)

    async def delete(self, credential_id: str) -> dict[str, Any]:
        ref = self._refs.pop(credential_id, None)
        if ref is not None:
            key = self._key(
                credential_id=ref.credential_id,
                scope_level=ref.scope.level,
                agent_id=ref.scope.agent_id,
            )
            self._values.pop(key, None)
        _log_credential_audit(
            operation="delete",
            credential_id=credential_id,
            kind=ref.kind if ref is not None else None,
            scope_level=ref.scope.level if ref is not None else None,
            agent_id=ref.scope.agent_id if ref is not None else None,
            deleted=ref is not None,
        )
        return {"ok": True, "deleted": ref is not None, "credential_id": credential_id}

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id:
            return None
        if not kind:
            return None
        ref = self._refs.get(credential_id)
        if ref is None:
            return None
        if ref.kind.strip() != kind:
            return None
        agent_id = None
        if isinstance(scope_context, dict) and isinstance(scope_context.get("agent_id"), str):
            agent_id = scope_context["agent_id"].strip()
        if agent_id:
            agent_key = self._key(credential_id=credential_id, scope_level="agent", agent_id=agent_id)
            if agent_key in self._values:
                return self._values[agent_key]
        global_key = self._key(credential_id=credential_id, scope_level="global", agent_id=None)
        return self._values.get(global_key)
