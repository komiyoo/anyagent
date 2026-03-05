#!/usr/bin/env python3
from __future__ import annotations

"""
Builds a minimal, plain-text manifest for docs progressive disclosure.

Output format (TSV, comment lines start with '#'):
  path<TAB>doc_kind<TAB>status<TAB>tags(comma)<TAB>summary<TAB>req(comma)

The manifest is designed to be:
- extremely small and agent-friendly (no JSON brackets/quotes noise)
- mechanically checkable (file coverage, broken paths)
- usable as a "docs harness" entrypoint before loading full documents
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable


_RAW_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HTML_COMMENT_FRONT_MATTER_RE = re.compile(
    r"\A<!--\s*\n---\s*\n(.*?)\n---\s*\n-->\s*\n", re.DOTALL
)


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


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\s]+", value) if p.strip()]
        return sorted(set(parts))
    if isinstance(value, list):
        parts = [str(p).strip() for p in value if str(p).strip()]
        return sorted(set(parts))
    return []


def _normalize_reqs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\s]+", value) if p.strip()]
        return sorted(set(parts))
    if isinstance(value, list):
        parts = [str(p).strip() for p in value if str(p).strip()]
        return sorted(set(parts))
    return []


def _infer_kind_status(rel: Path, meta: dict[str, Any]) -> dict[str, Any]:
    if rel.as_posix() == "docs/README.md":
        meta.setdefault("doc_kind", "docs")
        meta.setdefault("status", "stable")
        return meta
    if rel.as_posix() == "docs/AGENTS.md":
        meta.setdefault("doc_kind", "harness")
        meta.setdefault("status", "stable")
        return meta

    if len(rel.parts) >= 2 and rel.parts[0] == "docs":
        if rel.parts[1] == "acceptance":
            meta.setdefault("doc_kind", "acceptance")
            meta.setdefault("status", "stable")
        elif rel.parts[1] == "architecture":
            meta.setdefault("doc_kind", "architecture")
            meta.setdefault("status", "stable")
        elif rel.parts[1] == "security":
            meta.setdefault("doc_kind", "security")
            meta.setdefault("status", "stable")
        elif rel.parts[1] == "performance":
            meta.setdefault("doc_kind", "performance")
            meta.setdefault("status", "stable")
        elif rel.parts[1] == "_dev":
            meta.setdefault("doc_kind", "dev")
            meta.setdefault("status", "wip")
        elif rel.parts[1] == "_notes":
            meta.setdefault("doc_kind", "notes")
            meta.setdefault("status", "stable")
    return meta


def _clean_one_line(text: str) -> str:
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _iter_docs_markdown(root: Path, include_notes: bool) -> Iterable[Path]:
    docs_dir = root / "docs"
    if not docs_dir.exists():
        return []

    allow_prefixes = [
        docs_dir / "README.md",
        docs_dir / "AGENTS.md",
        docs_dir / "acceptance",
        docs_dir / "architecture",
        docs_dir / "security",
        docs_dir / "performance",
        docs_dir / "_dev",
    ]
    if include_notes:
        allow_prefixes.append(docs_dir / "_notes")

    candidates: list[Path] = []
    for prefix in allow_prefixes:
        if prefix.is_file():
            candidates.append(prefix)
        elif prefix.is_dir():
            candidates.extend(p for p in prefix.rglob("*.md") if p.is_file())

    # stable order
    return sorted(set(candidates))


def _build_lines(
    root: Path, include_notes: bool, max_summary_chars: int
) -> list[str]:
    lines: list[str] = []
    for path in _iter_docs_markdown(root, include_notes=include_notes):
        rel = path.relative_to(root)
        if rel.as_posix() == "docs/_manifest.txt":
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        meta = _extract_front_matter(text)
        meta = _infer_kind_status(rel, meta)
        _title, inferred_summary = _extract_title_and_summary(text)

        doc_kind = _clean_one_line(str(meta.get("doc_kind") or ""))
        status = _clean_one_line(str(meta.get("status") or ""))
        tags = ",".join(_normalize_tags(meta.get("tags")))
        reqs = ",".join(_normalize_reqs(meta.get("req")))
        summary = _clean_one_line(str(meta.get("summary") or inferred_summary or ""))
        if max_summary_chars > 0 and len(summary) > max_summary_chars:
            summary = summary[: max_summary_chars - 1].rstrip() + "…"

        lines.append(
            "\t".join(
                [
                    rel.as_posix(),
                    doc_kind,
                    status,
                    tags,
                    summary,
                    reqs,
                ]
            )
        )

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Build docs manifest (plain text).")
    parser.add_argument("--root", default=".", help="repo root (default: .)")
    parser.add_argument(
        "--output",
        default="docs/_manifest.txt",
        help="output path, relative to root (default: docs/_manifest.txt)",
    )
    parser.add_argument(
        "--include-notes",
        action="store_true",
        help="include docs/_notes in the manifest",
    )
    parser.add_argument(
        "--max-summary-chars",
        type=int,
        default=160,
        help="truncate summary to this length (default: 160; 0 disables)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print to stdout instead of writing file",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 2

    out_path = (root / args.output).resolve()
    try:
        out_path.relative_to(root)
    except ValueError:
        print(f"output must be inside repo: {out_path}", file=sys.stderr)
        return 2

    body = _build_lines(
        root=root,
        include_notes=args.include_notes,
        max_summary_chars=args.max_summary_chars,
    )

    header = [
        "# anyagent docs manifest v1",
        "# fields: path<TAB>doc_kind<TAB>status<TAB>tags(comma)<TAB>summary<TAB>req(comma)",
        "# regenerate: python3 scripts/docs/index.py --root .",
        "",
    ]
    content = "\n".join(header + body) + "\n"

    if args.stdout:
        sys.stdout.write(content)
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"docs_index: wrote {out_path.relative_to(root)} ({len(body)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
