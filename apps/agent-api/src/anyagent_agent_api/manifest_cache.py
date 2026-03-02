from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManifestCacheEntry:
    tools: list[dict[str, Any]]
    toolset_version: int
    expires_at: float


class ManifestCache:
    def __init__(self, *, ttl_seconds: float) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._entries: dict[str, ManifestCacheEntry] = {}

    def _make_key(
        self,
        *,
        agent_id: str,
        session_key: str | None,
        enabled_skills: list[str] | None,
        requested_tool_names: list[str] | None,
        context: dict[str, Any] | None,
    ) -> str:
        enabled = sorted([s.strip() for s in (enabled_skills or []) if isinstance(s, str) and s.strip()])
        requested = sorted([s.strip() for s in (requested_tool_names or []) if isinstance(s, str) and s.strip()])
        context_obj = context or {}
        context_json = json.dumps(context_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        raw = json.dumps(
            {
                "agent_id": agent_id,
                "session_key": session_key,
                "enabled_skills": enabled,
                "requested_tool_names": requested,
                "context": context_json,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(
        self,
        *,
        agent_id: str,
        session_key: str | None,
        enabled_skills: list[str] | None,
        requested_tool_names: list[str] | None,
        context: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], int] | None:
        if self._ttl_seconds <= 0:
            return None

        key = self._make_key(
            agent_id=agent_id,
            session_key=session_key,
            enabled_skills=enabled_skills,
            requested_tool_names=requested_tool_names,
            context=context,
        )
        entry = self._entries.get(key)
        if entry is None:
            return None

        if time.monotonic() >= entry.expires_at:
            self._entries.pop(key, None)
            return None

        return copy.deepcopy(entry.tools), entry.toolset_version

    def put(
        self,
        *,
        agent_id: str,
        session_key: str | None,
        enabled_skills: list[str] | None,
        requested_tool_names: list[str] | None,
        context: dict[str, Any] | None,
        tools: list[dict[str, Any]],
        toolset_version: int,
    ) -> None:
        if self._ttl_seconds <= 0:
            return

        key = self._make_key(
            agent_id=agent_id,
            session_key=session_key,
            enabled_skills=enabled_skills,
            requested_tool_names=requested_tool_names,
            context=context,
        )
        self._entries[key] = ManifestCacheEntry(
            tools=copy.deepcopy(tools),
            toolset_version=toolset_version,
            expires_at=time.monotonic() + self._ttl_seconds,
        )

    def invalidate_all(self) -> None:
        self._entries.clear()
