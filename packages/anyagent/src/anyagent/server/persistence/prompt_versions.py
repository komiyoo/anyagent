from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from anyagent.protocol.prompt_versions import PromptVersionSnapshot


class JsonPromptVersionStore:
    def __init__(self, *, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()
        self._lock = threading.Lock()

    async def append(self, snapshot: PromptVersionSnapshot) -> PromptVersionSnapshot:
        with self._lock:
            payload = self._read_unlocked()
            versions = payload.setdefault("versions", {})
            agent_versions = versions.setdefault(snapshot.agent_id, [])
            if not isinstance(agent_versions, list):
                agent_versions = []
                versions[snapshot.agent_id] = agent_versions
            agent_versions.append(snapshot.model_dump(mode="json", exclude_none=True))
            self._write_unlocked(payload)
        return snapshot

    async def list(self, *, agent_id: str, limit: int = 100) -> list[PromptVersionSnapshot]:
        payload = self._read()
        versions = payload.get("versions", {}).get(agent_id, [])
        items = [PromptVersionSnapshot.model_validate(item) for item in versions if isinstance(item, dict)]
        items.sort(key=lambda item: (item.created_at_ms, item.version_id), reverse=True)
        return items[: max(1, min(int(limit), 500))]

    async def get(self, *, agent_id: str, version_id: str) -> PromptVersionSnapshot | None:
        for item in await self.list(agent_id=agent_id, limit=500):
            if item.version_id == version_id:
                return item
        return None

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"versions": {}}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"versions": {}}
        if not isinstance(loaded, dict):
            return {"versions": {}}
        loaded.setdefault("versions", {})
        return loaded

    def _write_unlocked(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
