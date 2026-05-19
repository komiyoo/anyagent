from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReplayFilters:
    """Represent query filters for rollout replay."""

    session_partition_key: str | None
    response_id: str | None
    kinds: set[str]
    last_seq: int
    limit: int


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for rollout replay."""
    p = argparse.ArgumentParser(description="Replay local rollout.jsonl records for observability and debugging.")
    p.add_argument("--root-dir", default=None, help="Rollout root directory (default: env ROLLOUT_ROOT_DIR or WORKSPACE_DIR/.runs/rollouts).")
    p.add_argument("--workspace-dir", default=None, help="Workspace root used when --root-dir is not set (default: env WORKSPACE_DIR or cwd).")
    p.add_argument("--session-partition-key", default=None, help="Filter by exact session_partition_key.")
    p.add_argument("--response-id", default=None, help="Filter by exact response_id.")
    p.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable).")
    p.add_argument("--last-seq", type=int, default=0, help="Event replay cursor: only return event_appended with seq > last_seq.")
    p.add_argument("--limit", type=int, default=200, help="Max records to return (default: 200, max: 5000).")
    p.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format.")
    p.add_argument("--include-fingerprint", action="store_true", help="Include per-record fingerprint in output.")
    return p.parse_args(argv)


def resolve_rollout_root_dir(*, root_dir: str | None, workspace_dir: str | None) -> Path:
    """Resolve rollout root directory using args/env defaults."""
    rd = (root_dir or "").strip() or (os.getenv("ROLLOUT_ROOT_DIR") or "").strip()
    if rd:
        p = Path(rd).expanduser()
        if p.is_absolute():
            return p
        ws = _resolve_workspace_dir(workspace_dir)
        return (ws / p).resolve()
    ws = _resolve_workspace_dir(workspace_dir)
    return (ws / ".runs" / "rollouts").resolve()


def _resolve_workspace_dir(workspace_dir: str | None) -> Path:
    """Resolve workspace directory using args/env defaults."""
    ws = (workspace_dir or "").strip() or (os.getenv("WORKSPACE_DIR") or "").strip()
    if not ws:
        ws = "."
    return Path(ws).expanduser().resolve()


def _normalize_kinds(raw: list[str] | None) -> set[str]:
    """Normalize repeated --kind inputs into a non-empty string set."""
    out: set[str] = set()
    for v in raw or []:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if s:
            out.add(s)
    return out


def _build_filters(ns: argparse.Namespace) -> ReplayFilters:
    """Build validated replay filters from parsed args."""
    limit = int(ns.limit) if isinstance(ns.limit, int) else 200
    limit = max(1, min(5000, limit))
    last_seq = int(ns.last_seq) if isinstance(ns.last_seq, int) else 0
    last_seq = max(0, last_seq)
    return ReplayFilters(
        session_partition_key=ns.session_partition_key.strip() if isinstance(ns.session_partition_key, str) and ns.session_partition_key.strip() else None,
        response_id=ns.response_id.strip() if isinstance(ns.response_id, str) and ns.response_id.strip() else None,
        kinds=_normalize_kinds(ns.kind),
        last_seq=last_seq,
        limit=limit,
    )


def _iter_rollout_files(root_dir: Path) -> list[Path]:
    """List rollout jsonl files under root directory in deterministic order."""
    if not root_dir.exists():
        return []
    files = [
        p
        for p in root_dir.rglob("rollout*.jsonl")
        if p.is_file() and (p.name == "rollout.jsonl" or p.name.startswith("rollout-"))
    ]
    return sorted(files, key=lambda p: str(p))


def _match_record(row: dict[str, Any], filters: ReplayFilters) -> bool:
    """Return True when one rollout record matches all filters."""
    if filters.session_partition_key is not None and row.get("session_partition_key") != filters.session_partition_key:
        return False
    if filters.response_id is not None and row.get("response_id") != filters.response_id:
        return False
    kind = row.get("kind")
    if filters.kinds and (not isinstance(kind, str) or kind not in filters.kinds):
        return False
    if kind == "event_appended":
        seq = row.get("seq")
        if not isinstance(seq, int):
            return False
        if seq <= filters.last_seq:
            return False
    return True


def _record_view(row: dict[str, Any], *, include_fingerprint: bool, source_file: Path, source_line: int) -> dict[str, Any]:
    """Return sanitized replay output record."""
    out = dict(row)
    if not include_fingerprint:
        out.pop("fingerprint", None)
    out["_source"] = {"file": str(source_file), "line": source_line}
    return out


def _replay(*, root_dir: Path, filters: ReplayFilters, include_fingerprint: bool) -> dict[str, Any]:
    """Replay rollout records from local files with filtering and limits."""
    files = _iter_rollout_files(root_dir)
    scanned_lines = 0
    parse_errors = 0
    matched = 0
    next_last_seq = filters.last_seq
    records: list[dict[str, Any]] = []

    for fp in files:
        with fp.open("r", encoding="utf-8") as fh:
            for ln, line in enumerate(fh, start=1):
                scanned_lines += 1
                s = line.strip()
                if not s:
                    continue
                try:
                    row = json.loads(s)
                except Exception:  # noqa: BLE001
                    parse_errors += 1
                    continue
                if not isinstance(row, dict):
                    continue
                if not _match_record(row, filters):
                    continue
                matched += 1
                if row.get("kind") == "event_appended" and isinstance(row.get("seq"), int):
                    next_last_seq = max(next_last_seq, int(row["seq"]))
                if len(records) < filters.limit:
                    records.append(_record_view(row, include_fingerprint=include_fingerprint, source_file=fp, source_line=ln))

    return {
        "root_dir": str(root_dir),
        "filters": {
            "session_partition_key": filters.session_partition_key,
            "response_id": filters.response_id,
            "kinds": sorted(filters.kinds),
            "last_seq": filters.last_seq,
            "limit": filters.limit,
        },
        "summary": {
            "files": len(files),
            "scanned_lines": scanned_lines,
            "parse_errors": parse_errors,
            "matched": matched,
            "returned": len(records),
            "truncated": matched > len(records),
            "next_last_seq": next_last_seq,
        },
        "records": records,
    }


def replay_rollout_records(*, root_dir: Path, filters: ReplayFilters, include_fingerprint: bool = False) -> dict[str, Any]:
    """Replay local rollout records with filtering and cursor semantics."""
    return _replay(root_dir=root_dir, filters=filters, include_fingerprint=include_fingerprint)


def main(argv: list[str] | None = None) -> int:
    """Run rollout replay CLI and print results."""
    ns = _parse_args(list(argv) if isinstance(argv, list) else sys.argv[1:])
    filters = _build_filters(ns)
    root_dir = resolve_rollout_root_dir(root_dir=ns.root_dir, workspace_dir=ns.workspace_dir)
    result = replay_rollout_records(root_dir=root_dir, filters=filters, include_fingerprint=bool(ns.include_fingerprint))

    if ns.format == "jsonl":
        print(json.dumps({"summary": result["summary"]}, ensure_ascii=False))
        for row in result["records"]:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
