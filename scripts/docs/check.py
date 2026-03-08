#!/usr/bin/env python3
from __future__ import annotations

"""
Checks Markdown links, inline file references, and TODO evidence for drift.

This script is intentionally lightweight (stdlib only) so it can be used as a
mechanical guardrail to reduce doc entropy over time.
"""

import argparse
import re
import sys
from pathlib import Path
from pathlib import PurePosixPath


_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_IMPL_PATH_LINE_RE = re.compile(r"([A-Za-z0-9_./-]+):([0-9]{1,9})")
_CODE_PATH_LINE_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"((?:\.\./|\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)"
    r"(?::([0-9]{1,9}))?"
    r"(?![A-Za-z0-9_])"
)
_MANIFEST_REL = Path("docs/_manifest.txt")
_SKIP_DIR_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".runs",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
_REPO_TOP_LEVEL_NAMES = {
    ".agents",
    ".github",
    "apps",
    "docs",
    "examples",
    "packages",
    "plugins",
    "scripts",
    "tests",
    "todo",
}


def _is_external_link(target: str) -> bool:
    return (
        "://" in target
        or target.startswith("mailto:")
        or target.startswith("tel:")
        or target.startswith("data:")
    )


def _iter_markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []

    for md_path in root.rglob("*.md"):
        if not md_path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in md_path.parts):
            continue
        candidates.append(md_path)

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


def _resolve_reference_path(root: Path, owner_path: Path, raw_path: str) -> Path | None:
    candidates = [
        (root / raw_path).resolve(),
        (owner_path.parent / raw_path).resolve(),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None


def _looks_like_repo_reference(raw_path: str, raw_line: str | None) -> bool:
    if "..." in raw_path or "*" in raw_path:
        return False

    parts = [part for part in PurePosixPath(raw_path).parts if part not in {".", ".."}]
    if not parts:
        return False

    first_part = parts[0]
    if raw_line is not None:
        return True
    if first_part in _REPO_TOP_LEVEL_NAMES:
        return True
    if len(parts) >= 2 and parts[0].startswith("anyagent-") and parts[1] in _REPO_TOP_LEVEL_NAMES:
        return True
    return False


def _validate_reference(
    *,
    root: Path,
    owner_path: Path,
    owner_line: int | None,
    raw_path: str,
    raw_line: str | None,
    label: str,
) -> list[str]:
    errors: list[str] = []
    rel_owner = owner_path.relative_to(root)
    resolved = _resolve_reference_path(root, owner_path, raw_path)
    location = f"{rel_owner}:{owner_line}" if owner_line is not None else str(rel_owner)
    target_desc = f"{raw_path}:{raw_line}" if raw_line else raw_path

    if resolved is None:
        errors.append(f"{location}: {label} missing -> {target_desc}")
        return errors

    if raw_line is None:
        return errors

    if not resolved.is_file():
        errors.append(f"{location}: {label} not a file -> {target_desc}")
        return errors

    try:
        total_lines = _count_file_lines(resolved)
    except OSError:
        errors.append(f"{location}: {label} unreadable -> {target_desc}")
        return errors

    try:
        referenced_line = int(raw_line)
    except ValueError:
        errors.append(f"{location}: {label} bad line -> {target_desc}")
        return errors

    if referenced_line < 1 or referenced_line > max(total_lines, 1):
        errors.append(
            f"{location}: {label} line out of range -> "
            f"{target_desc} (file has {total_lines} lines)"
        )

    return errors


def _check_inline_code_references(root: Path, md_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        lines = md_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        rel = md_path.relative_to(root)
        return [f"{rel}: unreadable (non-utf8?)"]

    seen: set[tuple[int, str, str | None]] = set()
    for line_idx, line in enumerate(lines, start=1):
        for code_match in _INLINE_CODE_RE.finditer(line):
            inline_code = code_match.group(1).strip()
            if not inline_code or "://" in inline_code or "*" in inline_code:
                continue

            for path_match in _CODE_PATH_LINE_RE.finditer(inline_code):
                raw_path = path_match.group(1)
                raw_line = path_match.group(2)
                if not _looks_like_repo_reference(raw_path, raw_line):
                    continue
                token_key = (line_idx, raw_path, raw_line)
                if token_key in seen:
                    continue
                seen.add(token_key)

                if path_match.start() >= 2 and inline_code[path_match.start() - 2 : path_match.start()] == "//":
                    continue
                if any(ch in raw_path for ch in "<>$"):
                    continue

                errors.extend(
                    _validate_reference(
                        root=root,
                        owner_path=md_path,
                        owner_line=line_idx,
                        raw_path=raw_path,
                        raw_line=raw_line,
                        label="inline file ref",
                    )
                )

    return errors


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

                errors.extend(
                    _validate_reference(
                        root=root,
                        owner_path=todo_path,
                        owner_line=idx,
                        raw_path=file_part,
                        raw_line=line_part,
                        label="Impl evidence",
                    )
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
    parser.add_argument(
        "--check-code-refs",
        action="store_true",
        help="also validate inline `path` / `path:line` references in markdown",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for md_path in _iter_markdown_files(root):
        errors.extend(_check_markdown_links(root, md_path))
        if args.check_code_refs:
            errors.extend(_check_inline_code_references(root, md_path))

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
