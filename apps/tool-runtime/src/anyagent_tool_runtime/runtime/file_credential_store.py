from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anyagent.protocol.credential_vault import CredentialScope
from anyagent.protocol.tool_runtime import AuthRef

from .credential_store import CredentialStore, _validate_credential_id


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
        created_at = existing.created_at if existing is not None else now

        payload = {
            "credential_id": credential_id,
            "kind": kind,
            "value": value,
            "scope": scope.model_dump(exclude_none=True),
            "metadata": dict(metadata or {}),
            "created_at": created_at,
            "updated_at": now,
        }
        _atomic_write_json(path, payload)

    async def resolve(self, auth_ref: AuthRef, scope_context: dict[str, Any] | None = None) -> str | None:
        credential_id = (auth_ref.ref or "").strip()
        kind = (auth_ref.kind or "").strip()
        if not credential_id or not kind:
            return None

        agent_id = None
        if scope_context is not None:
            agent_id = scope_context.get("agent_id")

        # 1) agent scope
        if isinstance(agent_id, str) and agent_id.strip():
            agent_scope = CredentialScope(level="agent", agent_id=agent_id.strip())
            agent_path = self._path_for(scope=agent_scope, credential_id=credential_id)
            entry = _read_credential_file(agent_path)
            if entry is not None and entry.kind == kind:
                return entry.value

        # 2) global scope
        global_scope = CredentialScope(level="global")
        global_path = self._path_for(scope=global_scope, credential_id=credential_id)
        entry = _read_credential_file(global_path)
        if entry is not None and entry.kind == kind:
            return entry.value

        # 3) env fallback (compat)
        env_var = f"CREDENTIAL__{credential_id.upper()}"
        v = self._environ.get(env_var)
        if v:
            return v
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
            for p in agents_root.glob(f"*/{credential_id}.json"):
                try:
                    p.unlink()
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


def _scope_matches(*, filter_scope: CredentialScope, entry_scope: CredentialScope) -> bool:
    if filter_scope.level == "global":
        return entry_scope.level == "global"
    if filter_scope.level == "agent":
        return entry_scope.level == "agent" and entry_scope.agent_id == filter_scope.agent_id
    return False


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
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(data, encoding="utf-8")

    # Ensure file permissions are strict, regardless of umask.
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

