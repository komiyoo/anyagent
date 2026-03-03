#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal


Direction = Literal["callers", "callees", "both"]
OutFormat = Literal["md", "json", "text"]

CACHE_VERSION = 1

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    ".cache",
}


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def find_repo_root(start: Path) -> Path:
    rc, out = _run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if rc == 0:
        root = out.strip()
        if root:
            return Path(root)
    return start.resolve()


def iter_python_files(root: Path) -> list[Path]:
    rc, out = _run(["git", "ls-files", "*.py"], cwd=root)
    if rc == 0 and out.strip():
        files: list[Path] = []
        for line in out.splitlines():
            p = (root / line.strip()).resolve()
            if p.is_file():
                files.append(p)
        return files

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(dirpath) / fn)
    return files


def module_name_for_path(root: Path, file_path: Path) -> str:
    rel_path = file_path.resolve().relative_to(root.resolve())
    parts = list(rel_path.parts)
    # Common repo layout: <proj>/(apps|packages)/<name>/src/<py_pkg>/...
    if "src" in parts:
        i = parts.index("src")
        parts = parts[i + 1 :]
        rel = Path(*parts).as_posix() if parts else ""
    else:
        rel = rel_path.as_posix()
    if rel.endswith(".py"):
        rel = rel[: -len(".py")]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def tags_for_path(path: str) -> list[str]:
    p = path.replace("\\", "/")
    tags: list[str] = []
    if "/apps/agent-api/" in p:
        tags.append("agent-api")
    if "/apps/tool-runtime/" in p:
        tags.append("tool-runtime")
    if "/packages/anyagent/" in p:
        tags.append("anyagent")
    for t in ("protocol", "storage", "gateway", "skills", "tool_runtime", "agent_runtime", "clients", "internal"):
        if f"/{t}/" in p or p.endswith(f"/{t}.py"):
            tags.append(t)
    # Dedup stable order
    out: list[str] = []
    for t in tags:
        if t not in out:
            out.append(t)
    return out


@dataclass(frozen=True, slots=True)
class DefInfo:
    qualname: str
    file: str
    line: int | None
    kind: Literal["function", "method", "class"]
    summary: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModuleImports:
    module_aliases: dict[str, str]
    name_aliases: dict[str, str]


@dataclass(frozen=True, slots=True)
class Index:
    repo_root: str
    defs: dict[str, DefInfo]
    imports: dict[str, ModuleImports]  # module -> imports
    callees: dict[str, list[str]]  # caller qualname -> list[callee token/qualname]
    callers: dict[str, list[str]]  # callee qualname/token -> list[caller qualname]
    unresolved_edges: list[tuple[str, str]]


def _doc_summary(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    first = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return first


def _safe_get_end_lineno(node: ast.AST) -> int | None:
    end = getattr(node, "end_lineno", None)
    return int(end) if isinstance(end, int) else None


def _attribute_chain(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _attribute_chain(expr.value)
        if not base:
            return None
        return f"{base}.{expr.attr}"
    return None


def _iter_calls(node: ast.AST) -> Iterator[str]:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        name = _attribute_chain(sub.func)
        if name:
            yield name


def _parse_module_imports(tree: ast.AST) -> ModuleImports:
    module_aliases: dict[str, str] = {}
    name_aliases: dict[str, str] = {}

    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                asname = alias.asname or alias.name.split(".")[-1]
                module_aliases[asname] = mod
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            mod = node.module
            for alias in node.names:
                if alias.name == "*":
                    continue
                asname = alias.asname or alias.name
                name_aliases[asname] = f"{mod}.{alias.name}"

    return ModuleImports(module_aliases=module_aliases, name_aliases=name_aliases)


def _resolve_token(
    *,
    token: str,
    module: str,
    current_class: str | None,
    defs_set: set[str],
    imports: ModuleImports | None,
    simple_to_defs: dict[str, list[str]],
) -> str:
    # 1) from-import aliases (Name token)
    if imports and token in imports.name_aliases:
        candidate = imports.name_aliases[token]
        if candidate in defs_set:
            return candidate

    # 2) self./cls. method calls
    if current_class and (token.startswith("self.") or token.startswith("cls.")):
        method = token.split(".", 1)[1]
        candidate = f"{current_class}.{method}"
        if candidate in defs_set:
            return candidate

    # 3) module alias: alias.something -> full.module.something
    if imports and "." in token:
        base, rest = token.split(".", 1)
        if base in imports.module_aliases:
            candidate = f"{imports.module_aliases[base]}.{rest}"
            if candidate in defs_set:
                return candidate
        if base in imports.name_aliases:
            candidate = f"{imports.name_aliases[base]}.{rest}"
            if candidate in defs_set:
                return candidate

    # 4) Class.method within same module
    if "." in token:
        first, rest = token.split(".", 1)
        candidate = f"{module}.{first}.{rest}"
        if candidate in defs_set:
            return candidate

    # 5) simple name unique
    if "." not in token:
        cands = simple_to_defs.get(token) or []
        if len(cands) == 1:
            return cands[0]

    # 6) already qualified
    if token in defs_set:
        return token

    return token


def _enclosing_def_at_line(file_path: Path, *, line: int) -> tuple[str, ast.AST] | None:
    try:
        src = file_path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    best: tuple[int, str, ast.AST] | None = None  # span, qual, node

    def visit(node: ast.AST, prefix: str) -> None:
        nonlocal best
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = getattr(child, "lineno", None)
                end = _safe_get_end_lineno(child)
                if isinstance(start, int) and end is not None and start <= line <= end:
                    qual = f"{prefix}.{child.name}" if prefix else child.name
                    span = end - start
                    if best is None or span < best[0]:
                        best = (span, qual, child)
                    visit(child, qual)
                else:
                    visit(child, f"{prefix}.{child.name}" if prefix else child.name)

    visit(tree, "")
    if best is None:
        return None
    return best[1], best[2]


def build_index(
    *,
    repo_root: Path,
    py_files: list[Path],
) -> Index:
    defs: dict[str, DefInfo] = {}
    imports: dict[str, ModuleImports] = {}
    raw_calls: dict[str, list[tuple[str, str | None, str]]] = {}  # caller -> (module, current_class, token)

    for fp in py_files:
        try:
            src = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        module = module_name_for_path(repo_root, fp)
        imports[module] = _parse_module_imports(tree)

        def add_def(qual: str, node: ast.AST, kind: DefInfo.kind) -> None:
            lineno = getattr(node, "lineno", None)
            line = int(lineno) if isinstance(lineno, int) else None
            info = DefInfo(
                qualname=qual,
                file=str(fp.resolve().relative_to(repo_root.resolve())).replace("\\", "/"),
                line=line,
                kind=kind,
                summary=_doc_summary(node),
                tags=tuple(tags_for_path(str(fp))),
            )
            defs[qual] = info

        for node in getattr(tree, "body", []):
            if isinstance(node, ast.ClassDef):
                cls_qual = f"{module}.{node.name}" if module else node.name
                add_def(cls_qual, node, "class")
                for sub in getattr(node, "body", []):
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_qual = f"{cls_qual}.{sub.name}"
                        add_def(m_qual, sub, "method")
                        raw_calls.setdefault(m_qual, [])
                        for tok in _iter_calls(sub):
                            raw_calls[m_qual].append((module, cls_qual, tok))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_qual = f"{module}.{node.name}" if module else node.name
                add_def(fn_qual, node, "function")
                raw_calls.setdefault(fn_qual, [])
                for tok in _iter_calls(node):
                    raw_calls[fn_qual].append((module, None, tok))

    defs_set = set(defs.keys())
    simple_to_defs: dict[str, list[str]] = {}
    for qual in defs_set:
        simple = qual.split(".")[-1]
        simple_to_defs.setdefault(simple, []).append(qual)

    callees_map: dict[str, list[str]] = {}
    callers_map: dict[str, list[str]] = {}
    unresolved_edges: list[tuple[str, str]] = []

    for caller, calls in raw_calls.items():
        resolved: list[str] = []
        for mod, current_class, tok in calls:
            module_imports = imports.get(mod)
            callee = _resolve_token(
                token=tok,
                module=mod,
                current_class=current_class,
                defs_set=defs_set,
                imports=module_imports,
                simple_to_defs=simple_to_defs,
            )
            resolved.append(callee)
            if callee not in defs_set:
                unresolved_edges.append((caller, callee))
            callers_map.setdefault(callee, []).append(caller)
        callees_map[caller] = resolved

    # Dedup callers lists
    for k, v in list(callers_map.items()):
        seen: set[str] = set()
        out: list[str] = []
        for x in v:
            if x not in seen:
                seen.add(x)
                out.append(x)
        callers_map[k] = out

    return Index(
        repo_root=str(repo_root),
        defs=defs,
        imports=imports,
        callees=callees_map,
        callers=callers_map,
        unresolved_edges=unresolved_edges,
    )


def _cache_path(repo_root: Path, cache_dir: Path | None) -> Path:
    if cache_dir is not None:
        return cache_dir / "index.json"
    return repo_root / ".cache" / "repo-symbol-trace" / "index.json"


def _load_cache(path: Path) -> Index | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("cache_version") != CACHE_VERSION:
        return None
    try:
        defs = {
            k: DefInfo(
                qualname=v["qualname"],
                file=v["file"],
                line=v.get("line"),
                kind=v["kind"],
                summary=v.get("summary", ""),
                tags=tuple(v.get("tags", [])),
            )
            for k, v in data["defs"].items()
        }
        imports: dict[str, ModuleImports] = {}
        for mod, v in data.get("imports", {}).items():
            imports[mod] = ModuleImports(
                module_aliases=dict(v.get("module_aliases", {})),
                name_aliases=dict(v.get("name_aliases", {})),
            )
        return Index(
            repo_root=data["repo_root"],
            defs=defs,
            imports=imports,
            callees={k: list(v) for k, v in data["callees"].items()},
            callers={k: list(v) for k, v in data["callers"].items()},
            unresolved_edges=[tuple(x) for x in data.get("unresolved_edges", [])],
        )
    except Exception:
        return None


def _save_cache(path: Path, index: Index) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cache_version": CACHE_VERSION,
        "repo_root": index.repo_root,
        "defs": {
            k: {
                "qualname": v.qualname,
                "file": v.file,
                "line": v.line,
                "kind": v.kind,
                "summary": v.summary,
                "tags": list(v.tags),
            }
            for k, v in index.defs.items()
        },
        "imports": {
            k: {"module_aliases": v.module_aliases, "name_aliases": v.name_aliases}
            for k, v in index.imports.items()
        },
        "callees": index.callees,
        "callers": index.callers,
        "unresolved_edges": [list(x) for x in index.unresolved_edges],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _score_entrypoint(defs: dict[str, DefInfo], qual: str) -> int:
    info = defs.get(qual)
    if not info:
        return 1000
    p = info.file
    score = 100
    if p.endswith("__main__.py"):
        score -= 50
    if p.endswith("main.py"):
        score -= 30
    if p.endswith("app.py"):
        score -= 20
    if "/internal/" in p:
        score += 10
    if "/clients/" in p:
        score += 10
    return score


def _iter_paths(
    next_nodes: callable,
    start: str,
    *,
    depth: int,
    max_paths: int,
) -> list[list[str]]:
    paths: list[list[str]] = []

    def dfs(node: str, path: list[str], depth_left: int) -> None:
        if len(paths) >= max_paths:
            return
        if depth_left <= 0:
            paths.append(path[:])
            return
        nxt = next_nodes(node)
        if not nxt:
            paths.append(path[:])
            return
        extended = False
        for n in nxt:
            if n in path:
                continue
            extended = True
            path.append(n)
            dfs(n, path, depth_left - 1)
            path.pop()
            if len(paths) >= max_paths:
                return
        if not extended:
            paths.append(path[:])

    dfs(start, [start], depth)
    # Dedup while preserving order (paths are small).
    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []
    for p in paths:
        key = tuple(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _render_node(defs: dict[str, DefInfo], qual: str) -> str:
    info = defs.get(qual)
    if not info:
        return f"{qual} — [unresolved]"
    loc = f"{info.file}:{info.line}" if info.line else info.file
    summary = info.summary
    tags = ",".join(info.tags)
    tag_part = f" [tags: {tags}]" if tags else ""
    dash = " — " if summary else ""
    return f"{qual} ({loc}){dash}{summary}{tag_part}"

def _print_paths(
    *,
    title: str,
    paths: list[list[str]],
    defs: dict[str, DefInfo],
    is_md: bool,
    header_prefix: str,
) -> None:
    if not paths:
        return
    print(f"{header_prefix} {title}".rstrip())
    for i, path in enumerate(paths, 1):
        if is_md:
            print(f"- Path #{i}")
            for node in path:
                print(f"  - {_render_node(defs, node)}")
        else:
            print(f"Path #{i}")
            for node in path:
                print(f"  - {_render_node(defs, node)}")
        print()


def _select_target(
    *,
    index: Index,
    symbol: str | None,
    file: str | None,
    line: int | None,
    pick: int | None,
) -> tuple[str, list[str]]:
    defs = index.defs
    file_filter = file.replace("\\", "/").lstrip("./") if isinstance(file, str) and file.strip() else None

    if file and line:
        repo_root = Path(index.repo_root)
        fp = (repo_root / file).resolve()
        enc = _enclosing_def_at_line(fp, line=line)
        if enc:
            module = module_name_for_path(repo_root, fp)
            qual = f"{module}.{enc[0]}" if module else enc[0]
            if qual in defs:
                return qual, []

    if not symbol:
        raise SystemExit("missing target: use --symbol or --file+--line")

    # module:qualname
    if ":" in symbol:
        mod, name = symbol.split(":", 1)
        candidate = f"{mod}.{name}" if mod else name
        if candidate in defs:
            return candidate, []

    # exact qualname
    if symbol in defs:
        if file_filter and defs[symbol].file != file_filter:
            raise SystemExit(f"symbol found but not in --file: {symbol} (expected {file_filter})")
        return symbol, []

    # match by suffix / simple name
    candidates = [q for q in defs.keys() if q.endswith(f".{symbol}") or q.split(".")[-1] == symbol]
    if file_filter:
        candidates = [q for q in candidates if defs[q].file == file_filter]
    if len(candidates) == 1:
        return candidates[0], []
    if not candidates:
        raise SystemExit(f"symbol not found: {symbol}")

    candidates = sorted(candidates)
    if pick is None:
        return "", candidates
    if pick < 1 or pick > len(candidates):
        raise SystemExit(f"--pick out of range: {pick} (1..{len(candidates)})")
    return candidates[pick - 1], []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="repo_symbol_trace.py")
    p.add_argument("--symbol", type=str, default=None, help="symbol name or module:qualname")
    p.add_argument("--file", type=str, default=None, help="file path (repo-relative) for line->def inference")
    p.add_argument("--line", type=int, default=None, help="1-based line number for --file inference")
    p.add_argument("--pick", type=int, default=None, help="pick Nth candidate when ambiguous (1-based)")
    p.add_argument("--direction", type=str, choices=["callers", "callees", "both"], default="both")
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--max-paths", type=int, default=20)
    p.add_argument("--format", type=str, choices=["md", "json", "text"], default="md")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--cache-dir", type=str, default=None)
    args = p.parse_args(argv)

    repo_root = find_repo_root(Path.cwd())
    cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else None
    cache_path = _cache_path(repo_root, cache_dir)

    cache_hit = False
    index: Index | None = None
    if not args.no_cache and cache_path.exists():
        index = _load_cache(cache_path)
        cache_hit = index is not None

    if index is None:
        py_files = iter_python_files(repo_root)
        index = build_index(repo_root=repo_root, py_files=py_files)
        if not args.no_cache:
            _save_cache(cache_path, index)

    try:
        target, candidates = _select_target(
            index=index,
            symbol=args.symbol,
            file=args.file,
            line=args.line,
            pick=args.pick,
        )
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    if not target:
        # Ambiguous without pick
        if args.format in {"md", "text"}:
            print("Ambiguous symbol; candidates (use --pick N):")
            for i, q in enumerate(candidates, 1):
                print(f"{i:>2}. {_render_node(index.defs, q)}")
        else:
            payload = {
                "target": None,
                "candidates": [
                    {
                        "qualname": q,
                        "path": index.defs[q].file,
                        "line": index.defs[q].line,
                        "summary": index.defs[q].summary,
                    }
                    for q in candidates
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    depth = max(0, int(args.depth))
    max_paths = max(1, int(args.max_paths))
    defs_set = set(index.defs.keys())

    callers_paths: list[list[str]] = []
    callees_paths: list[list[str]] = []

    if args.direction in {"callers", "both"}:
        paths = _iter_paths(
            lambda n: [c for c in index.callers.get(n, []) if c in defs_set],
            target,
            depth=depth,
            max_paths=max_paths,
        )
        # Paths are target->... callers; reverse for display and rank
        rev = [list(reversed(x)) for x in paths]
        rev.sort(key=lambda path: (_score_entrypoint(index.defs, path[0]), len(path)))
        callers_paths = rev

    if args.direction in {"callees", "both"}:
        paths = _iter_paths(
            lambda n: [c for c in index.callees.get(n, []) if c in defs_set],
            target,
            depth=depth,
            max_paths=max_paths,
        )
        paths.sort(key=lambda path: (len(path), path[-1]))
        callees_paths = paths

    if args.format == "json":
        nodes: dict[str, Any] = {}
        for q, info in index.defs.items():
            nodes[q] = {
                "path": info.file,
                "line": info.line,
                "summary": info.summary,
                "tags": list(info.tags),
            }
        payload = {
            "target": {
                "qualname": target,
                "path": index.defs[target].file if target in index.defs else None,
                "line": index.defs[target].line if target in index.defs else None,
            },
            "candidates": [],
            "paths": {"callers": callers_paths, "callees": callees_paths},
            "nodes": nodes,
            "unresolved_edges": [{"caller": a, "callee": b} for a, b in index.unresolved_edges],
            "stats": {
                "files": len(iter_python_files(Path(index.repo_root))),
                "defs": len(index.defs),
                "edges": sum(len(v) for v in index.callees.values()),
                "cache": {"hit": cache_hit, "path": str(cache_path) if not args.no_cache else None},
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # md/text
    is_md = args.format == "md"
    h1 = "##" if is_md else ""
    print(f"{h1} Target")
    print(_render_node(index.defs, target))
    print()

    print(f"{h1} Stats")
    edges = sum(len(v) for v in index.callees.values())
    cache_msg = f"hit={cache_hit} path={cache_path}" if not args.no_cache else "disabled"
    print(f"- defs: {len(index.defs)}")
    print(f"- edges: {edges}")
    print(f"- cache: {cache_msg}")
    print()

    if callers_paths:
        _print_paths(
            title="Callers paths",
            paths=callers_paths,
            defs=index.defs,
            is_md=is_md,
            header_prefix=h1,
        )

    if callees_paths:
        _print_paths(
            title="Callees paths",
            paths=callees_paths,
            defs=index.defs,
            is_md=is_md,
            header_prefix=h1,
        )

    if index.unresolved_edges:
        print(f"{h1} Unresolved edges (sample)")
        noisy = 0
        shown = 0
        for a, b in index.unresolved_edges:
            # Reduce noise: prioritize dotted tokens (likely methods/modules) over builtins like `set`, `dict`, etc.
            if "." not in b:
                noisy += 1
                continue
            print(f"- {a} -> {b}" if is_md else f"{a} -> {b}")
            shown += 1
            if shown >= 20:
                break
        if noisy:
            suffix = f"(suppressed {noisy} non-dotted tokens)"
            print(f"- {suffix}" if is_md else suffix)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
