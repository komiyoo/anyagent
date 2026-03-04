from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any

from .models import SessionRecord


_SAFE_DIR_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_ROLLOUT_FILE_RE = re.compile(r"^rollout(?:-\d{17}(?:-\d+)?)?\.jsonl$")


def _now_ms() -> int:
    """Return current unix time in milliseconds."""
    return int(time() * 1000)


def _sha256_text(value: str) -> str:
    """Return SHA256 hex digest for a UTF-8 text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Dump JSON in a canonical one-line representation for stable hashing (best-effort)."""
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:  # noqa: BLE001
        # Fallback for non-JSON values: keep it stable and safe.
        return json.dumps({"repr": repr(obj)}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_clone(obj: Any) -> Any:
    """Return a JSON-safe deep copy."""
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _summarize_text(value: Any, *, preview_max_chars: int = 200, max_object_keys: int = 32) -> dict[str, Any]:
    """
    Summarize text-like content with length/hash and a safe preview.

    Security:
    - Never write raw content previews into rollout files.
    - Only include structure-only previews (e.g., object keys, list length).
    """

    s = value if isinstance(value, str) else _canonical_json(value)

    preview: str | None = None
    truncated = False

    if isinstance(value, dict):
        keys_all = sorted([k for k in value.keys() if isinstance(k, str)])
        keys = keys_all[:max_object_keys]
        preview = ("object keys: " + ",".join(keys)) if keys else None
        truncated = len(keys_all) > max_object_keys
    elif isinstance(value, list):
        preview = f"list length: {len(value)}"
    elif isinstance(value, str):
        try:
            obj = json.loads(value)
        except Exception:  # noqa: BLE001
            obj = None
        if isinstance(obj, dict):
            keys_all = sorted([k for k in obj.keys() if isinstance(k, str)])
            keys = keys_all[:max_object_keys]
            preview = ("object keys: " + ",".join(keys)) if keys else None
            truncated = len(keys_all) > max_object_keys

    if isinstance(preview, str) and len(preview) > preview_max_chars:
        preview = preview[:preview_max_chars]
        truncated = True

    return {"length": len(s), "sha256": _sha256_text(s), "preview": preview, "truncated": truncated}


def _build_session_dirname(session_partition_key: str) -> str:
    """Build a deterministic filesystem-safe directory name from a session key."""
    base = _SAFE_DIR_RE.sub("-", session_partition_key).strip("-")
    if not base:
        base = "session"
    if len(base) > 64:
        base = base[:64].rstrip("-")
    suffix = _sha256_text(session_partition_key)[:12]
    return f"{base}--{suffix}"


def _extract_session_record(row: dict[str, Any]) -> SessionRecord | None:
    """Decode a `session_snapshot_upserted` rollout row into `SessionRecord`."""
    try:
        return SessionRecord(
            session_partition_key=str(row["session_partition_key"]),
            agent_id=str(row["agent_id"]),
            session_key=str(row["session_key"]),
            snapshot_json=_json_clone(row["snapshot_json"]) if isinstance(row.get("snapshot_json"), dict) else {},
            snapshot_version=int(row["snapshot_version"]),
        )
    except Exception:  # noqa: BLE001
        return None


@dataclass
class _SessionRolloutState:
    """Hold in-memory state for one session rollout file."""

    file_path: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    seen_fingerprints: set[str] = field(default_factory=set)
    latest_session_snapshot: SessionRecord | None = None
    loaded: bool = False


class RolloutFileWriter:
    """Append rollout records to session-scoped `rollout*.jsonl` files with write-time dedupe."""

    def __init__(
        self,
        *,
        root_dir: Path,
        max_file_bytes: int = 0,
        max_file_age_seconds: int = 0,
        max_rotated_files: int = 16,
    ) -> None:
        """Create a rollout writer rooted at `root_dir`."""
        self._root_dir = root_dir
        self._max_file_bytes = max(0, int(max_file_bytes))
        self._max_file_age_seconds = max(0, int(max_file_age_seconds))
        self._max_rotated_files = max(1, int(max_rotated_files))
        self._states_lock = asyncio.Lock()
        self._states: dict[str, _SessionRolloutState] = {}

    @property
    def root_dir(self) -> Path:
        """Return the rollout root directory."""
        return self._root_dir

    async def append_run_started(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        idempotency_key: str | None,
        stream: bool,
    ) -> bool:
        """Append one `run_started` record if it has not been written before."""
        stable = {
            "kind": "run_started",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "idempotency_key": idempotency_key,
            "stream": bool(stream),
            "status": "started",
        }
        payload = {"ts_ms": _now_ms(), **stable}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"run_started:{response_id}",
            payload=payload,
            dedupe_payload=stable,
        )

    async def append_run_final(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> bool:
        """Append one `run_final` record if the same final snapshot was not written before."""
        stable = {
            "kind": "run_final",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "status": status,
            "final_response_json": final_response_json,
            "error_json": error_json,
        }
        payload = {"ts_ms": _now_ms(), **stable}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"run_final:{response_id}",
            payload=payload,
            dedupe_payload=stable,
        )

    async def append_event_appended(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        seq: int,
        event: str | None,
        data: str,
    ) -> bool:
        """Append one event record if the same event identity was not written before."""
        stable = {
            "kind": "event_appended",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "seq": int(seq),
            "event": event,
            "data": data,
            "data_sha256": _sha256_text(data),
        }
        payload = {"ts_ms": _now_ms(), **stable}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"event:{response_id}:{int(seq)}",
            payload=payload,
            dedupe_payload=stable,
        )

    async def append_turn_started(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        turn_index: int,
        previous_response_id: str | None,
        mode: str,
    ) -> bool:
        """Append one `turn_started` record."""
        stable = {
            "kind": "turn_started",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "turn_index": int(turn_index),
            "previous_response_id": previous_response_id,
            "mode": mode,
        }
        payload = {"ts_ms": _now_ms(), **stable}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"turn_started:{response_id}:{int(turn_index)}",
            payload=payload,
            dedupe_payload=stable,
        )

    async def append_turn_completed(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        turn_index: int,
        status: str,
        function_call_count: int,
        output_item_count: int | None,
    ) -> bool:
        """Append one `turn_completed` record."""
        stable = {
            "kind": "turn_completed",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "turn_index": int(turn_index),
            "status": status,
            "function_call_count": int(function_call_count),
            "output_item_count": int(output_item_count) if output_item_count is not None else None,
        }
        payload = {"ts_ms": _now_ms(), **stable}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"turn_completed:{response_id}:{int(turn_index)}:{status}",
            payload=payload,
            dedupe_payload=stable,
        )

    async def append_item_observed(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        turn_index: int,
        item_type: str,
        item_id: str | None,
        payload: Any,
    ) -> bool:
        """Append one `item_observed` record with payload summary only."""
        payload_summary = _summarize_text(payload)
        stable = {
            "kind": "item_observed",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "turn_index": int(turn_index),
            "item_type": item_type,
            "item_id": item_id,
            "payload_sha256": payload_summary["sha256"],
        }
        row = {"ts_ms": _now_ms(), **stable, "payload_summary": payload_summary}
        item_key = item_id or payload_summary["sha256"][:16]
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"item:{response_id}:{int(turn_index)}:{item_type}:{item_key}",
            payload=row,
            dedupe_payload=stable,
        )

    async def append_tool_call_requested(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        turn_index: int,
        tool_call_id: str,
        tool_name: str,
        arguments_json: Any,
        is_system_tool: bool,
    ) -> bool:
        """Append one `tool_call_requested` record with summarized arguments."""
        args_summary = _summarize_text(arguments_json)
        stable = {
            "kind": "tool_call_requested",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "turn_index": int(turn_index),
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "is_system_tool": bool(is_system_tool),
            "arguments_sha256": args_summary["sha256"],
        }
        row = {"ts_ms": _now_ms(), **stable, "arguments_summary": args_summary}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"tool_call_requested:{response_id}:{tool_call_id}",
            payload=row,
            dedupe_payload=stable,
        )

    async def append_tool_call_completed(
        self,
        *,
        session_partition_key: str,
        response_id: str,
        turn_index: int,
        tool_call_id: str,
        tool_name: str,
        status: str,
        output: Any,
        error: Any,
    ) -> bool:
        """Append one `tool_call_completed` record with summarized output/error."""
        output_summary = _summarize_text(output if output is not None else "")
        err_summary = _summarize_text(error if error is not None else "")
        stable = {
            "kind": "tool_call_completed",
            "session_partition_key": session_partition_key,
            "response_id": response_id,
            "turn_index": int(turn_index),
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": status,
            "output_sha256": output_summary["sha256"],
            "error_sha256": err_summary["sha256"],
        }
        row = {"ts_ms": _now_ms(), **stable, "output_summary": output_summary, "error_summary": err_summary}
        return await self._append(
            session_partition_key=session_partition_key,
            identity_key=f"tool_call_completed:{response_id}:{tool_call_id}",
            payload=row,
            dedupe_payload=stable,
        )

    async def load_session_snapshot(self, *, session_partition_key: str) -> SessionRecord | None:
        """Load the latest session snapshot from rollout history."""
        state = await self._get_or_create_state(session_partition_key=session_partition_key)
        async with state.lock:
            await self._ensure_loaded(state)
            rec = state.latest_session_snapshot
            if rec is None:
                return None
            return SessionRecord.model_validate(rec.model_dump())

    async def append_session_snapshot_upserted(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int,
    ) -> tuple[bool, SessionRecord | None]:
        """CAS-append a new session snapshot row and return the latest snapshot."""
        state = await self._get_or_create_state(session_partition_key=session_partition_key)
        async with state.lock:
            await self._ensure_loaded(state)
            current = state.latest_session_snapshot
            current_version = -1 if current is None else int(current.snapshot_version)

            if current is None:
                if int(expected_snapshot_version) != 0:
                    return False, None
                next_version = 0
            else:
                if current_version != int(expected_snapshot_version):
                    return False, SessionRecord.model_validate(current.model_dump())
                next_version = current_version + 1

            stable = {
                "kind": "session_snapshot_upserted",
                "session_partition_key": session_partition_key,
                "agent_id": agent_id,
                "session_key": session_key,
                "snapshot_version": next_version,
                "snapshot_json": _json_clone(snapshot_json),
            }
            fp = _sha256_text(f"session_snapshot:{session_partition_key}:{next_version}|{_canonical_json(stable)}")
            if fp in state.seen_fingerprints:
                rec = _extract_session_record(stable)
                if rec is not None:
                    state.latest_session_snapshot = rec
                    return True, SessionRecord.model_validate(rec.model_dump())
                return False, SessionRecord.model_validate(current.model_dump()) if current is not None else None

            state.file_path.parent.mkdir(parents=True, exist_ok=True)
            await self._rotate_if_needed(state)
            row = {"ts_ms": _now_ms(), **stable, "fingerprint": fp}
            with state.file_path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical_json(row))
                fh.write("\n")
            state.seen_fingerprints.add(fp)
            rec = _extract_session_record(row)
            if rec is not None:
                state.latest_session_snapshot = rec
                return True, SessionRecord.model_validate(rec.model_dump())
            return False, None

    async def _get_or_create_state(self, *, session_partition_key: str) -> _SessionRolloutState:
        """Return state holder for a session key, creating one if needed."""
        async with self._states_lock:
            st = self._states.get(session_partition_key)
            if st is not None:
                return st

            dirname = _build_session_dirname(session_partition_key)
            file_path = self._root_dir / dirname / "rollout.jsonl"
            st = _SessionRolloutState(file_path=file_path)
            self._states[session_partition_key] = st
            return st

    def _list_rollout_files(self, *, state: _SessionRolloutState) -> list[Path]:
        """List all rollout files for one session in deterministic order."""
        parent = state.file_path.parent
        if not parent.is_dir():
            return []

        rotated: list[Path] = []
        current: list[Path] = []
        for p in parent.iterdir():
            if not p.is_file() or not _ROLLOUT_FILE_RE.match(p.name):
                continue
            if p.name == "rollout.jsonl":
                current.append(p)
            else:
                rotated.append(p)
        rotated.sort(key=lambda x: x.name)
        current.sort(key=lambda x: x.name)
        return [*rotated, *current]

    async def _ensure_loaded(self, state: _SessionRolloutState) -> None:
        """Load historical fingerprints and latest session snapshot once."""
        if state.loaded:
            return
        try:
            for path in self._list_rollout_files(state=state):
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:  # noqa: BLE001
                            continue
                        fp = row.get("fingerprint")
                        if isinstance(fp, str) and fp:
                            state.seen_fingerprints.add(fp)
                        if row.get("kind") == "session_snapshot_upserted":
                            rec = _extract_session_record(row)
                            if rec is None:
                                continue
                            cur = state.latest_session_snapshot
                            if cur is None or int(rec.snapshot_version) >= int(cur.snapshot_version):
                                state.latest_session_snapshot = rec
        finally:
            state.loaded = True

    async def _rotate_if_needed(self, state: _SessionRolloutState) -> None:
        """Rotate current rollout file by size/time and keep a bounded history."""
        if not state.file_path.is_file():
            return
        if self._max_file_bytes <= 0 and self._max_file_age_seconds <= 0:
            return

        stat = state.file_path.stat()
        rotate_by_size = self._max_file_bytes > 0 and stat.st_size >= self._max_file_bytes
        rotate_by_age = self._max_file_age_seconds > 0 and (_now_ms() - int(stat.st_mtime * 1000)) >= (self._max_file_age_seconds * 1000)
        if not rotate_by_size and not rotate_by_age:
            return

        stamp = f"{_now_ms():017d}"
        target = state.file_path.parent / f"rollout-{stamp}.jsonl"
        i = 0
        while target.exists():
            i += 1
            target = state.file_path.parent / f"rollout-{stamp}-{i}.jsonl"
        state.file_path.rename(target)

        rotated = sorted(
            [
                p
                for p in state.file_path.parent.iterdir()
                if p.is_file() and p.name.startswith("rollout-") and p.name.endswith(".jsonl")
            ],
            key=lambda x: x.name,
        )
        if len(rotated) <= self._max_rotated_files:
            return
        for p in rotated[: len(rotated) - self._max_rotated_files]:
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                continue

    async def _append(
        self,
        *,
        session_partition_key: str,
        identity_key: str,
        payload: dict[str, Any],
        dedupe_payload: dict[str, Any] | None = None,
    ) -> bool:
        """Append one payload record with a write-time dedupe gate."""
        state = await self._get_or_create_state(session_partition_key=session_partition_key)
        async with state.lock:
            await self._ensure_loaded(state)
            fp_source = dedupe_payload if dedupe_payload is not None else payload
            fp = _sha256_text(identity_key + "|" + _canonical_json(fp_source))
            if fp in state.seen_fingerprints:
                return False

            state.file_path.parent.mkdir(parents=True, exist_ok=True)
            await self._rotate_if_needed(state)
            row = dict(payload)
            row["fingerprint"] = fp
            with state.file_path.open("a", encoding="utf-8") as fh:
                fh.write(_canonical_json(row))
                fh.write("\n")
            state.seen_fingerprints.add(fp)
            return True
