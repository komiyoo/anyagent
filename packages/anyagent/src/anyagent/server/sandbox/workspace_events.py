from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from anyagent.protocol.stage_events import AnyAgentWorkspaceLifecycleEvent


_SAFE_DIR_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _canonical_json(obj: object) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:  # noqa: BLE001
        return json.dumps({"repr": repr(obj)}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _build_session_dirname(session_partition_key: str) -> str:
    base = _SAFE_DIR_RE.sub("-", session_partition_key).strip("-")
    if not base:
        base = "session"
    if len(base) > 64:
        base = base[:64].rstrip("-")
    digest = hashlib.sha256(session_partition_key.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{base}--{digest}"


class WorkspaceEventStore(Protocol):
    async def append(self, event: AnyAgentWorkspaceLifecycleEvent) -> AnyAgentWorkspaceLifecycleEvent: ...

    async def list(
        self,
        *,
        session_partition_key: str | None = None,
        limit: int = 50,
    ) -> list[AnyAgentWorkspaceLifecycleEvent]: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class WorkspaceEventLog:
    """
    In-memory workspace lifecycle event buffer for admin/debug views.

    It is intentionally scoped to control-plane visibility. Agent loops see the
    resulting workspace behavior, not the infrastructure event log.
    """

    max_events: int = 512
    _events: deque[AnyAgentWorkspaceLifecycleEvent] = field(default_factory=deque)
    _next_seq: int = 1

    async def append(self, event: AnyAgentWorkspaceLifecycleEvent) -> AnyAgentWorkspaceLifecycleEvent:
        stored = event.model_copy(update={"seq": self._next_seq})
        self._next_seq += 1
        self._events.append(stored)
        while len(self._events) > self.max_events:
            self._events.popleft()
        return stored

    async def list(
        self,
        *,
        session_partition_key: str | None = None,
        limit: int = 50,
    ) -> list[AnyAgentWorkspaceLifecycleEvent]:
        items = list(self._events)
        if session_partition_key:
            items = [item for item in items if item.session_partition_key == session_partition_key]
        return items[-max(int(limit), 1) :]

    async def aclose(self) -> None:
        return None


@dataclass(slots=True)
class _WorkspaceEventFileState:
    file_path: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    events: list[AnyAgentWorkspaceLifecycleEvent] = field(default_factory=list)
    loaded: bool = False
    next_seq: int = 1


@dataclass(slots=True)
class JsonlWorkspaceEventStore:
    """
    Local jsonl audit sink for workspace lifecycle events.

    This is a reference durable event store for restart debugging. It does not
    try to be a cross-instance event bus or multi-process coordination layer.
    """

    root_dir: Path
    _states_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _states: dict[str, _WorkspaceEventFileState] = field(default_factory=dict)

    async def append(self, event: AnyAgentWorkspaceLifecycleEvent) -> AnyAgentWorkspaceLifecycleEvent:
        state = await self._get_or_create_state(session_partition_key=event.session_partition_key)
        async with state.lock:
            await self._ensure_loaded(state)
            stored = event.model_copy(update={"seq": state.next_seq})
            state.next_seq += 1
            state.file_path.parent.mkdir(parents=True, exist_ok=True)
            with state.file_path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical_json(stored.model_dump(mode="json", exclude_none=True)))
                fh.write("\n")
            state.events.append(stored)
            return stored

    async def list(
        self,
        *,
        session_partition_key: str | None = None,
        limit: int = 50,
    ) -> list[AnyAgentWorkspaceLifecycleEvent]:
        capped_limit = max(int(limit), 1)
        if session_partition_key:
            state = await self._get_or_create_state(session_partition_key=session_partition_key)
            async with state.lock:
                await self._ensure_loaded(state)
                return state.events[-capped_limit:]

        states = await self._all_states()
        items: list[AnyAgentWorkspaceLifecycleEvent] = []
        for state in states:
            async with state.lock:
                await self._ensure_loaded(state)
                items.extend(state.events)
        items.sort(key=lambda item: (item.ts_ms or 0, item.seq or 0))
        return items[-capped_limit:]

    async def aclose(self) -> None:
        return None

    async def _get_or_create_state(self, *, session_partition_key: str) -> _WorkspaceEventFileState:
        async with self._states_lock:
            file_path = self.root_dir / _build_session_dirname(session_partition_key) / "workspace-events.jsonl"
            state = self._states.get(session_partition_key)
            if state is not None:
                return state
            for existing in self._states.values():
                if existing.file_path == file_path:
                    self._states[session_partition_key] = existing
                    return existing
            state = _WorkspaceEventFileState(file_path=file_path)
            self._states[session_partition_key] = state
            return state

    async def _all_states(self) -> list[_WorkspaceEventFileState]:
        async with self._states_lock:
            states = list(self._states.values())
            if self.root_dir.is_dir():
                for child in self.root_dir.iterdir():
                    if not child.is_dir():
                        continue
                    file_path = child / "workspace-events.jsonl"
                    if not file_path.is_file():
                        continue
                    already_known = any(state.file_path == file_path for state in states)
                    if already_known:
                        continue
                    state = _WorkspaceEventFileState(file_path=file_path)
                    self._states[f"file:{file_path}"] = state
                    states.append(state)
            return states

    async def _ensure_loaded(self, state: _WorkspaceEventFileState) -> None:
        if state.loaded:
            return
        state.events.clear()
        max_seq = 0
        if state.file_path.is_file():
            with state.file_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                        event = AnyAgentWorkspaceLifecycleEvent.model_validate(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    state.events.append(event)
                    if isinstance(event.seq, int) and event.seq > max_seq:
                        max_seq = int(event.seq)
        state.next_seq = max_seq + 1
        state.loaded = True


def build_workspace_event_store(
    *,
    backend: str,
    root_dir: str | None,
    max_events: int,
) -> WorkspaceEventStore:
    resolved_backend = (backend or "memory").strip().lower()
    if resolved_backend == "jsonl":
        target_root = Path(root_dir or "/tmp/anyagent-tool-runtime-workspace-events").expanduser().resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        return JsonlWorkspaceEventStore(root_dir=target_root)
    return WorkspaceEventLog(max_events=max(int(max_events), 1))
