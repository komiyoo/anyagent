from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ManifestCacheKey:
    tenant_id: str | None
    agent_id: str
    session_key: str | None
    enabled_skills_hash: str
    requested_tool_names_hash: str
    context_hash: str


@dataclass(slots=True)
class _ManifestCacheEntry:
    value: tuple[list[dict[str, Any]], int]
    expires_at_monotonic: float


class ManifestCache:
    def __init__(self, *, ttl_seconds: float = 2.0) -> None:
        self._ttl_seconds = max(float(ttl_seconds), 0.0)
        self._entries: dict[ManifestCacheKey, _ManifestCacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: ManifestCacheKey) -> tuple[list[dict[str, Any]], int] | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at_monotonic < time.monotonic():
                self._entries.pop(key, None)
                return None
            tools, version = entry.value
            return (_clone_tools(tools), int(version))

    async def put(self, key: ManifestCacheKey, value: tuple[list[dict[str, Any]], int]) -> None:
        async with self._lock:
            self._entries[key] = _ManifestCacheEntry(
                value=(_clone_tools(value[0]), int(value[1])),
                expires_at_monotonic=time.monotonic() + self._ttl_seconds,
            )

    async def invalidate(self, key: ManifestCacheKey) -> None:
        async with self._lock:
            self._entries.pop(key, None)


def build_manifest_cache_key(
    *,
    tenant_id: str | None,
    agent_id: str,
    session_key: str | None,
    enabled_skills: list[str] | None,
    requested_tool_names: list[str] | None,
    context: dict[str, Any],
) -> ManifestCacheKey:
    return ManifestCacheKey(
        tenant_id=tenant_id.strip() if isinstance(tenant_id, str) and tenant_id.strip() else None,
        agent_id=agent_id,
        session_key=session_key.strip() if isinstance(session_key, str) and session_key.strip() else None,
        enabled_skills_hash=_stable_hash(
            sorted({s.strip() for s in (enabled_skills or []) if isinstance(s, str) and s.strip()})
        ),
        requested_tool_names_hash=_stable_hash(
            sorted({s.strip() for s in (requested_tool_names or []) if isinstance(s, str) and s.strip()})
        ),
        context_hash=_stable_hash(context if isinstance(context, dict) else {}),
    )


def extract_requested_tool_names(request_tools: Any) -> list[str] | None:
    if not isinstance(request_tools, list):
        return None
    out: list[str] = []
    for item in request_tools:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _stable_hash(value: Any) -> str:
    dumped = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _clone_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(tools, ensure_ascii=False))
