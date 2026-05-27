#!/usr/bin/env python3
from __future__ import annotations

"""
Packs a minimal, tag-filtered docs list for progressive disclosure.

Goal: avoid loading too much irrelevant context at once by allowing agents and
humans to quickly discover the smallest set of docs to read for a task.

This script uses a lightweight, optional YAML metadata block at the top of a
Markdown file. To avoid GitHub rendering the YAML as content, the recommended
convention is to wrap it in an HTML comment:

<!--
---
doc_kind: architecture
status: stable
tags: ["stateless", "idempotency"]
summary: One sentence summary.
req: ["requirements.md#req-7-1"]
---
-->
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


_RAW_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HTML_COMMENT_FRONT_MATTER_RE = re.compile(
    r"\A<!--\s*\n---\s*\n(.*?)\n---\s*\n-->\s*\n", re.DOTALL
)
@dataclass(frozen=True)
class DocEntry:
    path: Path
    meta: dict[str, Any]
    title: str
    summary: str


def _split_csv(value: str) -> list[str]:
    items = []
    for part in value.split(","):
        part = part.strip()
        if part:
            items.append(part)
    return items


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
    return value


def _parse_simple_yaml_block(block: str) -> dict[str, Any]:
    """
    Parses a small YAML subset suitable for doc metadata.

    Supported:
    - key: value
    - key:
        - item
        - item
    - inline lists: ["a", "b"]
    """

    meta: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue

        if line.startswith(("  - ", "\t- ")):
            if current_key is None:
                continue
            meta.setdefault(current_key, [])
            if isinstance(meta[current_key], list):
                meta[current_key].append(line.split("-", 1)[1].strip().strip("'\""))
            continue

        current_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            current_key = key
            meta[key] = []
        else:
            meta[key] = _parse_scalar(value)

    return meta


def _extract_front_matter(text: str) -> dict[str, Any]:
    match = _HTML_COMMENT_FRONT_MATTER_RE.match(text) or _RAW_FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    return _parse_simple_yaml_block(match.group(1))


def _extract_title_and_summary(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    summary = ""
    if title:
        after_title = False
        for line in lines:
            if not after_title:
                if line.startswith("# "):
                    after_title = True
                continue
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "-", "*", ">")):
                continue
            summary = stripped
            break

    return title, summary


def _normalize_tags(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {t for t in re.split(r"[,\s]+", value.strip()) if t}
    if isinstance(value, list):
        return {str(t).strip() for t in value if str(t).strip()}
    return set()


def _load_index_entries(
    root: Path, include_notes: bool, index_path: Path
) -> list[DocEntry]:
    if not index_path.is_absolute():
        index_path = root / index_path
    if not index_path.exists():
        return []

    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []

    entries: list[DocEntry] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("\t")
        while len(parts) < 6:
            parts.append("")

        raw_path, doc_kind, status, raw_tags, summary, raw_req = parts[:6]
        if not raw_path:
            continue

        # Generated indexes may include notes; allow caller to exclude them.
        if not include_notes and (
            raw_path.startswith("docs/_notes/") or doc_kind.strip().lower() == "notes"
        ):
            continue

        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        req = [r.strip() for r in raw_req.split(",") if r.strip()]
        meta: dict[str, Any] = {
            "doc_kind": doc_kind.strip().lower(),
            "status": status.strip().lower(),
            "tags": tags,
            "req": req,
            "summary": summary.strip(),
        }
        entries.append(
            DocEntry(
                path=Path(raw_path),
                meta=meta,
                title="",
                summary=summary.strip(),
            )
        )

    return entries


def _status_rank(status: str) -> int:
    order = {
        "stable": 0,
        "wip": 1,
        "draft": 2,
        "deprecated": 3,
    }
    return order.get(status.strip().lower(), 9)


def _iter_candidate_docs(root: Path, include_notes: bool) -> Iterable[Path]:
    docs_dir = root / "docs"
    if not docs_dir.exists():
        return []

    preferred_dirs = [
        docs_dir / "acceptance",
        docs_dir / "architecture",
        docs_dir / "security",
        docs_dir / "performance",
        docs_dir / "_dev",
    ]
    if include_notes:
        preferred_dirs.append(docs_dir / "_notes")

    candidates: list[Path] = []
    for d in preferred_dirs:
        if d.exists():
            candidates.extend(p for p in d.rglob("*.md") if p.is_file())

    # also include docs/README.md for navigation
    if (docs_dir / "README.md").exists():
        candidates.append(docs_dir / "README.md")
    if (docs_dir / "AGENTS.md").exists():
        candidates.append(docs_dir / "AGENTS.md")

    return sorted(set(candidates))


def _load_entry(root: Path, path: Path) -> DocEntry | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    meta = _extract_front_matter(text)
    # Infer doc_kind/status from directory so the tool is useful even before
    # metadata is widely adopted.
    rel = path.relative_to(root)
    if rel.parts[:2] == ("docs", "acceptance"):
        meta.setdefault("doc_kind", "acceptance")
        meta.setdefault("status", "stable")
    elif rel.parts[:2] == ("docs", "architecture"):
        meta.setdefault("doc_kind", "architecture")
        meta.setdefault("status", "stable")
    elif rel.parts[:2] == ("docs", "security"):
        meta.setdefault("doc_kind", "security")
        meta.setdefault("status", "stable")
    elif rel.parts[:2] == ("docs", "performance"):
        meta.setdefault("doc_kind", "performance")
        meta.setdefault("status", "stable")
    elif rel.parts[:2] == ("docs", "_dev"):
        meta.setdefault("doc_kind", "dev")
        meta.setdefault("status", "wip")
    elif rel.parts[:2] == ("docs", "_notes"):
        meta.setdefault("doc_kind", "notes")
        meta.setdefault("status", "stable")

    title, inferred_summary = _extract_title_and_summary(text)
    summary = str(meta.get("summary") or inferred_summary or "").strip()

    return DocEntry(
        path=rel,
        meta=meta,
        title=title,
        summary=summary,
    )


def _filter_entries(
    entries: list[DocEntry],
    tags: set[str],
    kinds: set[str],
    statuses: set[str],
    include_untagged: bool,
) -> list[DocEntry]:
    result: list[DocEntry] = []

    for entry in entries:
        doc_kind = str(entry.meta.get("doc_kind") or "").strip().lower()
        status = str(entry.meta.get("status") or "").strip().lower()
        entry_tags = _normalize_tags(entry.meta.get("tags"))

        if kinds and doc_kind not in kinds:
            continue
        if statuses and status not in statuses:
            continue

        if tags:
            if entry_tags & tags:
                result.append(entry)
            elif include_untagged and not entry_tags:
                result.append(entry)
        else:
            result.append(entry)

    return result


def _sort_entries(entries: list[DocEntry]) -> list[DocEntry]:
    def key(e: DocEntry) -> tuple[int, str]:
        status = str(e.meta.get("status") or "")
        return (_status_rank(status), str(e.path))

    return sorted(entries, key=key)


def _print_list(entries: list[DocEntry], show_tags: bool) -> None:
    for e in entries:
        tags = sorted(_normalize_tags(e.meta.get("tags")))
        tags_part = f" (tags: {', '.join(tags)})" if show_tags and tags else ""
        summary_part = f" - {e.summary}" if e.summary else ""
        print(f"- {e.path}{tags_part}{summary_part}")


def _print_paths(entries: list[DocEntry]) -> None:
    for e in entries:
        print(str(e.path))


def _print_missing_meta(entries: list[DocEntry]) -> None:
    missing: list[str] = []
    for e in entries:
        meta = e.meta
        if not meta.get("tags") or not meta.get("summary"):
            missing.append(str(e.path))

    if not missing:
        print("docs_pack: all selected docs have tags+summary")
        return

    print("docs_pack: docs missing tags/summary")
    for p in missing:
        print(f"- {p}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack a minimal docs list by tags.")
    parser.add_argument("--root", default=".", help="repo root (default: .)")
    parser.add_argument(
        "--tags",
        default="",
        help="comma-separated tags to select (e.g. stateless,storage)",
    )
    parser.add_argument(
        "--kinds",
        default="",
        help="comma-separated doc_kind filter (e.g. architecture,security)",
    )
    parser.add_argument(
        "--statuses",
        default="",
        help="comma-separated status filter (e.g. stable,wip)",
    )
    parser.add_argument(
        "--include-notes",
        action="store_true",
        help="include docs/_notes in candidates",
    )
    parser.add_argument(
        "--index",
        default="",
        help="optional generated docs index TSV to read instead of scanning docs",
    )
    parser.add_argument(
        "--include-untagged",
        action="store_true",
        help="when tags filter is set, also include untagged docs",
    )
    parser.add_argument(
        "--format",
        choices=["list", "paths"],
        default="list",
        help="output format (default: list)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=12,
        help="max files to print (default: 12)",
    )
    parser.add_argument(
        "--show-tags",
        action="store_true",
        help="show tags in list output",
    )
    parser.add_argument(
        "--report-missing-meta",
        action="store_true",
        help="report selected docs missing tags/summary",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    tags = set(_split_csv(args.tags.lower())) if args.tags else set()
    kinds = set(_split_csv(args.kinds.lower())) if args.kinds else set()
    statuses = set(_split_csv(args.statuses.lower())) if args.statuses else set()

    entries: list[DocEntry] = []
    if args.index:
        entries = _load_index_entries(
            root,
            include_notes=args.include_notes,
            index_path=Path(args.index),
        )

    # Default to scanning files so generated indexes never become docs SSOT.
    if not entries:
        for path in _iter_candidate_docs(root, include_notes=args.include_notes):
            entry = _load_entry(root, path)
            if entry is not None:
                entries.append(entry)

    selected = _filter_entries(
        entries,
        tags=tags,
        kinds=kinds,
        statuses=statuses,
        include_untagged=args.include_untagged,
    )
    selected = _sort_entries(selected)[: max(args.max_files, 0)]

    if args.format == "paths":
        _print_paths(selected)
    else:
        _print_list(selected, show_tags=args.show_tags)

    if args.report_missing_meta:
        _print_missing_meta(selected)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
