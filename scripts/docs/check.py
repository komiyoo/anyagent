#!/usr/bin/env python3
from __future__ import annotations

"""
Checks Markdown links and TODO evidence references for drift.

This script is intentionally lightweight (stdlib only) so it can be used as a
mechanical guardrail to reduce doc entropy over time.
"""

import argparse
import re
import sys
from pathlib import Path


_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_IMPL_PATH_LINE_RE = re.compile(r"([A-Za-z0-9_./-]+):([0-9]{1,9})")
_MANIFEST_REL = Path("docs/_manifest.txt")


def _is_external_link(target: str) -> bool:
    return (
        "://" in target
        or target.startswith("mailto:")
        or target.startswith("tel:")
        or target.startswith("data:")
    )


def _iter_markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []

    for path in [root / "README.md", root / "AGENTS.md"]:
        if path.exists():
            candidates.append(path)

    for base in ["docs", "todo", "apps", "packages", "plugins"]:
        base_dir = root / base
        if not base_dir.exists():
            continue
        candidates.extend(p for p in base_dir.rglob("*.md") if p.is_file())

    # stable order for reproducible output
    return sorted(set(candidates))


def _iter_docs_for_manifest(root: Path, include_notes: bool) -> list[Path]:
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

    return sorted(set(candidates))


def _load_manifest_paths(root: Path) -> set[str]:
    manifest_path = root / _MANIFEST_REL
    if not manifest_path.exists():
        return set()

    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return set()

    paths: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        first = line.split("\t", 1)[0].strip()
        if first:
            paths.add(first)
    return paths


def _check_docs_manifest(root: Path, include_notes: bool) -> list[str]:
    errors: list[str] = []
    manifest_path = root / _MANIFEST_REL
    if not manifest_path.exists():
        errors.append(f"docs manifest missing -> {_MANIFEST_REL}")
        return errors

    manifest_paths = _load_manifest_paths(root)
    if not manifest_paths:
        errors.append(f"docs manifest unreadable/empty -> {_MANIFEST_REL}")
        return errors

    # 1) every manifest entry must exist
    for p in sorted(manifest_paths):
        if p == "docs/_manifest.txt":
            continue
        if not (root / p).exists():
            errors.append(f"docs manifest path missing -> {p}")

    # 2) every relevant docs/*.md should be present in manifest
    for doc in _iter_docs_for_manifest(root, include_notes=include_notes):
        rel = doc.relative_to(root).as_posix()
        if rel == "docs/_manifest.txt":
            continue
        if rel not in manifest_paths:
            errors.append(f"docs manifest missing entry -> {rel}")

    return errors


def _check_markdown_links(root: Path, md_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        content = md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # keep the checker usable even if a file is non-utf8; skip with a hint
        rel = md_path.relative_to(root)
        return [f"{rel}: unreadable (non-utf8?)"]

    for match in _MD_LINK_RE.finditer(content):
        raw_target = match.group(1).strip()
        if not raw_target:
            continue

        if raw_target.startswith("#"):
            continue

        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1].strip()

        if _is_external_link(raw_target):
            continue

        target = raw_target.split("#", 1)[0].split("?", 1)[0].strip()
        if not target:
            continue

        # Skip absolute paths (these are environment-specific).
        if target.startswith("/"):
            continue

        abs_target = (md_path.parent / target).resolve()
        try:
            abs_target.relative_to(root.resolve())
        except ValueError:
            rel = md_path.relative_to(root)
            errors.append(f"{rel}: link points outside repo -> {raw_target}")
            continue

        if not abs_target.exists():
            rel = md_path.relative_to(root)
            errors.append(f"{rel}: broken link -> {raw_target}")

    return errors


def _count_file_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def _check_todo_impl_evidence(root: Path) -> list[str]:
    errors: list[str] = []
    todo_dir = root / "todo"
    if not todo_dir.exists():
        return errors

    for todo_path in sorted(todo_dir.glob("*.md")):
        try:
            lines = todo_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            rel = todo_path.relative_to(root)
            errors.append(f"{rel}: unreadable (non-utf8?)")
            continue

        for idx, line in enumerate(lines, start=1):
            # Only validate evidence on completed TODO items; docs/examples may
            # mention `Impl:` with illustrative `path:line` that should not be
            # treated as a hard reference.
            if "Impl:" not in line or "- [x]" not in line.lower():
                continue

            for file_part, line_part in _IMPL_PATH_LINE_RE.findall(line):
                # normalize common diff prefixes (a/ b/)
                if file_part.startswith(("a/", "b/")):
                    file_part = file_part[2:]

                evidence_path = (root / file_part).resolve()
                rel_todo = todo_path.relative_to(root)
                if not evidence_path.exists():
                    errors.append(
                        f"{rel_todo}:{idx}: Impl evidence missing -> {file_part}:{line_part}"
                    )
                    continue

                if not evidence_path.is_file():
                    errors.append(
                        f"{rel_todo}:{idx}: Impl evidence not a file -> {file_part}:{line_part}"
                    )
                    continue

                try:
                    total_lines = _count_file_lines(evidence_path)
                except OSError:
                    errors.append(
                        f"{rel_todo}:{idx}: Impl evidence unreadable -> {file_part}:{line_part}"
                    )
                    continue

                try:
                    referenced_line = int(line_part)
                except ValueError:
                    errors.append(
                        f"{rel_todo}:{idx}: Impl evidence bad line -> {file_part}:{line_part}"
                    )
                    continue

                if referenced_line < 1 or referenced_line > max(total_lines, 1):
                    errors.append(
                        f"{rel_todo}:{idx}: Impl evidence line out of range -> "
                        f"{file_part}:{line_part} (file has {total_lines} lines)"
                    )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check docs links, TODO evidence, and optional docs manifest coverage."
    )
    parser.add_argument("--root", default=".", help="repo root (default: .)")
    parser.add_argument(
        "--check-manifest",
        action="store_true",
        help="also verify docs/_manifest.txt covers docs files",
    )
    parser.add_argument(
        "--include-notes",
        action="store_true",
        help="when --check-manifest, require docs/_notes entries too",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for md_path in _iter_markdown_files(root):
        errors.extend(_check_markdown_links(root, md_path))

    errors.extend(_check_todo_impl_evidence(root))
    if args.check_manifest:
        errors.extend(_check_docs_manifest(root, include_notes=args.include_notes))

    if errors:
        print("docs_check: FAIL")
        for e in errors:
            print(f"- {e}")
        return 1

    print("docs_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
