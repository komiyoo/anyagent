from __future__ import annotations

from typing import Any

from anyagent.mcp.auth import CredentialResolver
from anyagent.protocol.credential_vault import (
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)
from anyagent.protocol.tool_runtime import AuthRef


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
        return {"ok": True, "deleted": ref is not None, "credential_id": credential_id}

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        if not credential_id:
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
