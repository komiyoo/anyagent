#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
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
    "coverage",
    ".next",
    ".turbo",
    ".cache",
}


DEFAULT_CODE_EXTS = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".py",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".cs",
    ".rb",
    ".php",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".proto",
    ".sql",
}


MODULES = [
    "agent-api",
    "tool-runtime",
    "gateway",
    "concurrency",
    "security",
    "tests",
    "skills",
    "multi-agent",
]


def _sig(module: str, name: str) -> str:
    return f"{module}.{name}"


SIGNALS: dict[str, dict[str, list[str]]] = {
    "agent-api": {
        "responses_endpoint": [r"/v1/responses", r"POST\s+[/]v1[/]responses"],
        "sse_streaming": [r"text/event-stream", r"\bSSE\b", r"event:\s*\w+"],
        "auth": [r"Authorization:\s*Bearer", r"\bbearer\b", r"\bapi[_-]?key\b"],
        "idempotency": [r"Idempotency-Key", r"\bidempotenc(y|e)\b", r"\bdedupe\b"],
        "tools_loop": [
            r"\btool_choice\b",
            r"\bfunction_call\b",
            r"\bfunction_call_output\b",
            r"\bmanifest\b",
            r"tools\[\]",
        ],
        "agent_id_session_key": [
            r"\bagent[_-]?id\b",
            r"\bsession[_-]?key\b",
            r"session_partition_key",
        ],
    },
    "tool-runtime": {
        "manifest_api": [r"\bmanifest\b", r"/internal/tools/manifest", r"tools\.list"],
        "execute_api": [r"/internal/tools/execute", r"\btools\.execute\b", r"\bexecute_tool\b"],
        "tool_naming": [r"\btool[_-]?name\b", r"\bnamespace\b", r"\breserved\b"],
        "policy": [r"\bpolicy\b", r"\ballow\b", r"\bdeny\b", r"\bpermission(s)?\b"],
        "context_schema": [r"\bcontext\b", r"\bchannel\b", r"\bplatform\b"],
        "idempotency_abort_audit": [r"\bidempotenc(y|e)\b", r"\babort\b", r"\baudit\b", r"\btrace[_-]?id\b"],
        "sandbox": [r"\bsandbox\b", r"\bexec(ute)?\b", r"\bcode[_-]?execute\b"],
    },
    "gateway": {
        "connectors": [r"\bconnector\b", r"\bwebhook\b", r"\bevent\b", r"\bmessage\b"],
        "platforms": [r"\bfeishu\b", r"\blark\b", r"\bdiscord\b", r"\btelegram\b"],
        "rendering": [r"\brender\b", r"\bmarkdown\b", r"\bcard\b", r"\bembed\b"],
        "session_mapping": [r"\bsession[_-]?key\b", r"\bthread\b", r"\bchannel_id\b", r"\bchat_id\b"],
        "agent_routing": [r"\bagent[_-]?id\b", r"\bmapping\b", r"\broute\b"],
    },
    "concurrency": {
        "keyed_serialization": [r"session_partition_key", r"\bkeyed serialization\b", r"\block\b", r"\blease\b"],
        "queue_workers": [r"\bqueue\b", r"\bworker\b", r"\bdequeue\b", r"\benqueue\b"],
        "backpressure": [r"\bbackpressure\b", r"\bslow consumer\b", r"\bbuffer\b", r"\bdrop\b"],
        "retry_dedupe": [r"\bretry\b", r"\bdedupe\b", r"\bidempotenc(y|e)\b"],
    },
    "security": {
        "input_validation": [r"\bvalidate\b", r"\bsanitize\b", r"\bSSRF\b", r"\bpath traversal\b"],
        "authz": [r"\bauthz\b", r"\bauthoriz(e|ation)\b", r"\bpermission(s)?\b", r"\btenant\b"],
        "secrets": [r"\bsecret\b", r"\btoken\b", r"\bcredential\b", r"\bprivate key\b"],
        "audit_trace": [r"\baudit\b", r"\btrace[_-]?id\b", r"\bcorrelation\b"],
    },
    "tests": {
        "responses_compat": [r"\bresponses\b", r"\bcompat\b", r"\bSSE\b", r"\bstream\b"],
        "e2e_gateway": [r"\be2e\b", r"\bintegration\b", r"\bgateway\b"],
        "harness": [r"\bpytest\b", r"\bjest\b", r"\bvitest\b", r"\bgo test\b", r"\bcargo test\b"],
    },
    "skills": {
        "skills_loading": [r"\bSKILL\.md\b", r"\bskills\b", r"\bskill roots?\b", r"\bscope\b"],
        "dynamic_disclosure": [r"\bdynamic disclosure\b", r"\bdisclosure\b", r"\binject\b", r"\bselect\b"],
        "skills_list_api": [r"/internal/skills/list", r"\bskills\.list\b"],
        "permissions": [r"\bpermissions\b", r"\bpolicy\b", r"\ballow_implicit\b"],
    },
    "multi-agent": {
        "spawn": [r"\bspawn_agent\b"],
        "send_input": [r"\bsend_input\b"],
        "wait": [r"\bwait\s*\(", r"\btimeout_ms\b"],
        "close_resume": [r"\bclose_agent\b", r"\bresume_agent\b"],
        "governance": [r"\blimit\b", r"\bmax\b", r"\bdepth\b", r"\bgovern\b", r"\baudit\b"],
    },
}


SENSITIVE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)(api[_-]?key\\s*[:=]\\s*)([^\\s'\\\"]{6,})"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(token\\s*[:=]\\s*)([^\\s'\\\"]{6,})"), r"\1***REDACTED***"),
    (re.compile(r"(?i)(secret\\s*[:=]\\s*)([^\\s'\\\"]{6,})"), r"\1***REDACTED***"),
]


@dataclass(frozen=True)
class Hit:
    file: str
    line_no: int
    text: str


@dataclass(frozen=True)
class TodoItem:
    file: str
    line_no: int
    checked: bool
    text: str
    block_text: str = ""


@dataclass(frozen=True)
class Signal:
    module: str
    name: str
    pattern: re.Pattern[str]
    examples_limit: int

    @property
    def key(self) -> str:
        return _sig(self.module, self.name)


def redact(text: str) -> str:
    result = text.rstrip("\n")
    for pat, repl in SENSITIVE_REPLACEMENTS:
        result = pat.sub(repl, result)
    return result


def looks_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(2048)
        return b"\x00" in chunk
    except OSError:
        return True


def iter_candidate_files(
    root: str,
    *,
    include_md: bool,
    max_file_bytes: int,
    exclude_dirs: set[str],
    include_exts: set[str],
    exclude_paths_prefixes: list[str],
) -> Iterable[str]:
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""

        pruned: list[str] = []
        for d in dirnames:
            if d in exclude_dirs:
                continue
            if d.startswith(".") and d not in {".codex"}:
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for filename in filenames:
            if filename.startswith("."):
                continue

            path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(path, root)

            if any(rel_path == p or rel_path.startswith(p + os.sep) for p in exclude_paths_prefixes):
                continue

            _, ext = os.path.splitext(filename)
            if ext == ".md" and not include_md:
                continue
            if ext != ".md" and ext not in include_exts:
                continue

            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > max_file_bytes:
                continue
            if looks_binary(path):
                continue

            yield path


def detect_stack(root: str) -> list[str]:
    hints: list[str] = []
    candidates = [
        ("Node.js", "package.json"),
        ("Python", "pyproject.toml"),
        ("Python", "requirements.txt"),
        ("Go", "go.mod"),
        ("Rust", "Cargo.toml"),
        ("Java", "pom.xml"),
        ("Java", "build.gradle"),
        ("Docker", "docker-compose.yml"),
        ("Docker", "Dockerfile"),
    ]
    for label, rel in candidates:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            hints.append(f"{label}: {rel}")
    return hints


def parse_todo_progress(root: str) -> list[dict[str, object]]:
    todo_dir = os.path.join(root, "todo")
    if not os.path.isdir(todo_dir):
        return []

    heading_re = re.compile(r"^(#{1,6})\s+(.*)\s*$")
    checkbox_re = re.compile(r"^- \[( |x|X)\] ")
    impl_re = re.compile(r"\b(impl|实现)\s*:", re.IGNORECASE)
    module_re = re.compile(r"\b(module|模块)\s*:", re.IGNORECASE)

    def is_deferred_item(text: str) -> bool:
        # v2 规划项不应阻塞 v0/v1 的“下一条 TODO”提示。
        return "[v2]" in text

    def iter_items(path: str) -> tuple[list[TodoItem], list[TodoItem]]:
        """
        返回 (tasks_items, all_items)
        - tasks_items：尽量只统计“## 任务（Tasks）”段落下的 checkbox
        - all_items：兜底统计全文件 checkbox（用于没有 Tasks 段落的文件，例如 backlog）
        """
        tasks_items: list[TodoItem] = []
        all_items: list[TodoItem] = []

        in_tasks_section = False
        tasks_level: Optional[int] = None

        def append_item(item: TodoItem, *, belongs_to_tasks_section: bool) -> None:
            all_items.append(item)
            if belongs_to_tasks_section:
                tasks_items.append(item)

        current_item: Optional[TodoItem] = None
        current_block: list[str] = []
        current_in_tasks_section = False

        def flush_current() -> None:
            nonlocal current_item, current_block, current_in_tasks_section
            if current_item is None:
                return
            append_item(
                TodoItem(
                    file=current_item.file,
                    line_no=current_item.line_no,
                    checked=current_item.checked,
                    text=current_item.text,
                    block_text="\n".join(current_block),
                ),
                belongs_to_tasks_section=current_in_tasks_section,
            )
            current_item = None
            current_block = []
            current_in_tasks_section = False

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                m_heading = heading_re.match(line)
                if m_heading:
                    flush_current()
                    level = len(m_heading.group(1))
                    title = m_heading.group(2)
                    is_tasks = "任务" in title or "Tasks" in title

                    if is_tasks and level <= 3:
                        in_tasks_section = True
                        tasks_level = level
                    else:
                        # 退出 tasks 段：遇到同级或更高层级标题
                        if in_tasks_section and tasks_level is not None and level <= tasks_level:
                            in_tasks_section = False
                            tasks_level = None

                m = checkbox_re.match(line)
                if m:
                    flush_current()
                    checked = m.group(1).lower() == "x"
                    current_item = TodoItem(
                        file=os.path.relpath(path, root),
                        line_no=line_no,
                        checked=checked,
                        text=redact(line).strip(),
                    )
                    current_block = [redact(line).strip()]
                    current_in_tasks_section = in_tasks_section
                    continue

                if current_item is not None:
                    current_block.append(redact(line).strip())

        flush_current()

        return tasks_items, all_items

    results: list[dict[str, object]] = []
    for name in sorted(os.listdir(todo_dir)):
        if not name.endswith(".md"):
            continue
        if name in {"_template.md", "README.md"}:
            continue

        path = os.path.join(todo_dir, name)
        try:
            tasks_items, all_items = iter_items(path)
        except OSError:
            continue

        primary = tasks_items if tasks_items else all_items
        active = [it for it in primary if not is_deferred_item(it.text)]
        checked = sum(1 for it in active if it.checked)
        total = len(active)

        # 进度默认按“从上到下连续完成”理解：第一个未完成就是“当前/下一步”
        next_item: Optional[TodoItem] = None
        sequential_done = 0
        for it in active:
            if it.checked:
                sequential_done += 1
                continue
            next_item = it
            break

        missing_evidence: list[TodoItem] = []
        for it in active:
            if not it.checked:
                continue
            evidence_text = it.block_text or it.text
            if not impl_re.search(evidence_text) or not module_re.search(evidence_text):
                missing_evidence.append(it)

        try:
            rel = os.path.relpath(path, root)
        except Exception:
            rel = path

        results.append(
            {
                "file": rel,
                "mode": "tasks" if tasks_items else "all",
                "checked": checked,
                "total": total,
                "pct": 0 if total == 0 else round(100 * checked / total, 1),
                "sequential_done": sequential_done,
                "next_index": None if next_item is None else (sequential_done + 1),
                "next": None
                if next_item is None
                else {
                    "file": next_item.file,
                    "line": next_item.line_no,
                    "text": next_item.text,
                },
                "done_missing_evidence": len(missing_evidence),
                "missing_evidence_examples": [
                    {"file": it.file, "line": it.line_no, "text": it.text} for it in missing_evidence[:3]
                ],
            }
        )
    return results


def build_signals(*, examples_limit: int, requested_modules: set[str]) -> list[Signal]:
    signals: list[Signal] = []
    for module, by_name in SIGNALS.items():
        if module not in requested_modules:
            continue
        for name, pats in by_name.items():
            combined = "(" + ")|(".join(pats) + ")"
            signals.append(
                Signal(
                    module=module,
                    name=name,
                    pattern=re.compile(combined, re.IGNORECASE),
                    examples_limit=examples_limit,
                )
            )
    return signals


def scan(
    root: str,
    *,
    include_md: bool,
    max_file_bytes: int,
    max_files: int,
    examples_limit: int,
    requested_modules: set[str],
) -> dict[str, object]:
    root = os.path.abspath(root)
    signals = build_signals(examples_limit=examples_limit, requested_modules=requested_modules)

    # 默认只扫“实现代码”，避免被文档内容误导；需要扫文档时用 --include-md。
    # 注意：todo/ 默认始终不纳入线索扫描（它是“任务真源”，不是实现证据）。
    exclude_paths_prefixes = ["todo"]
    if not include_md:
        exclude_paths_prefixes += ["docs", "requirements.md", "README.md", "AGENTS.md"]
    exclude_paths_exact = {"scripts/anyagent_progress.py"}

    include_exts = set(DEFAULT_CODE_EXTS)
    if include_md:
        include_exts.add(".md")

    files_scanned = 0
    skipped_by_limit = 0

    counts: dict[str, int] = {s.key: 0 for s in signals}
    examples: dict[str, list[Hit]] = {s.key: [] for s in signals}
    file_scores_by_module: dict[str, dict[str, int]] = {m: {} for m in requested_modules}

    for path in iter_candidate_files(
        root,
        include_md=include_md,
        max_file_bytes=max_file_bytes,
        exclude_dirs=set(DEFAULT_EXCLUDE_DIRS),
        include_exts=include_exts,
        exclude_paths_prefixes=exclude_paths_prefixes,
    ):
        rel = os.path.relpath(path, root)
        if rel in exclude_paths_exact:
            continue
        if files_scanned >= max_files:
            skipped_by_limit += 1
            continue

        matched_any_in_file = False
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f, start=1):
                    for s in signals:
                        if not s.pattern.search(line):
                            continue
                        counts[s.key] += 1
                        matched_any_in_file = True
                        by_mod = file_scores_by_module.get(s.module)
                        if by_mod is not None:
                            by_mod[rel] = by_mod.get(rel, 0) + 1

                        if len(examples[s.key]) < s.examples_limit:
                            examples[s.key].append(Hit(file=rel, line_no=idx, text=redact(line)))
        except OSError:
            continue

        if matched_any_in_file:
            # 如果某个文件匹配很多信号，避免占用太多输出，交由 file_scores 汇总提示即可
            pass

        files_scanned += 1

    by_module: dict[str, dict[str, object]] = {}
    for module in requested_modules:
        if module not in SIGNALS:
            continue
        module_payload: dict[str, object] = {"signals": {}, "top_files": []}
        for name in SIGNALS[module].keys():
            k = _sig(module, name)
            module_payload["signals"][name] = {
                "count": counts.get(k, 0),
                "examples": [
                    {"file": h.file, "line": h.line_no, "text": h.text.strip()}
                    for h in examples.get(k, [])
                ],
            }
        top_files = sorted(
            (file_scores_by_module.get(module) or {}).items(),
            key=lambda kv: (-kv[1], kv[0]),
        )[:20]
        module_payload["top_files"] = [p for p, _ in top_files]
        by_module[module] = module_payload

    return {
        "root": root,
        "include_md": include_md,
        "scan_impl": True,
        "files_scanned": files_scanned,
        "skipped_by_limit": skipped_by_limit,
        "todo_progress": parse_todo_progress(root),
        "stack_hints": detect_stack(root),
        "modules": by_module,
    }


def compute_overall_next(todo_progress: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    从每个 todo 文件的“下一条”聚合出整体建议的下一步。
    默认顺序偏向核心模块（agent-api/tool-runtime/gateway...），backlog 最后。
    """

    def rank(path: str) -> int:
        order = [
            "todo/security-compliance.md",
            "todo/sdk.md",
        ]
        try:
            return order.index(path)
        except ValueError:
            return 999

    items: list[dict[str, object]] = []
    for it in todo_progress:
        nxt = it.get("next")
        if not nxt:
            continue
        items.append(
            {
                "file": it.get("file"),
                "next_index": it.get("next_index"),
                "next": nxt,
                "_rank": rank(str(it.get("file") or "")),
            }
        )

    items.sort(key=lambda x: (int(x["_rank"]), str(x.get("file") or "")))
    for x in items:
        x.pop("_rank", None)
    return items


def render_text(report: dict[str, object], *, requested_modules: list[str]) -> str:
    lines: list[str] = []
    lines.append("anyagent 进度线索扫描")
    lines.append(f"Root: {report['root']}")
    if "elapsed_ms" in report:
        lines.append(f"耗时: {report['elapsed_ms']}ms")
    if report.get("stack_hints"):
        lines.append("Stack Hints:")
        for h in report["stack_hints"]:
            lines.append(f"- {h}")
    if report.get("scan_impl"):
        lines.append(f"扫描文件: {report['files_scanned']}（超限跳过: {report['skipped_by_limit']}）")
        if int(report["files_scanned"]) == 0:
            lines.append("未扫描到候选实现文件（当前仓库可能以文档为主，或实现不在常见代码后缀中）。")
    else:
        lines.append("实现线索扫描：未启用（使用 `--scan-impl` 可开启，可选）。")

    todo = report.get("todo_progress") or []
    if todo:
        overall_next = compute_overall_next(todo)
        lines.append("")
        lines.append("TODO 进度（来自 todo/*.md）：")
        if overall_next:
            lines.append("- 整体下一步（按模块顺序）：")
            for x in overall_next[:6]:
                nxt = x["next"]
                lines.append(
                    f"  - {x['file']} 下一条（#{x.get('next_index')}）：{nxt['file']}:{nxt['line']} {nxt['text']}"
                )
        for it in todo:
            mode = it.get("mode") or "unknown"
            seq = it.get("sequential_done", 0)
            total = it.get("total", 0)
            checked = it.get("checked", 0)
            pct = it.get("pct", 0)
            lines.append(f"- {it['file']} [{mode}]: {checked}/{total} ({pct}%), 连续完成 {seq}")
            nxt = it.get("next")
            if nxt:
                lines.append(f"  - 下一条（#{it.get('next_index')}）：{nxt['file']}:{nxt['line']} {nxt['text']}")
            else:
                if total:
                    lines.append("  - 下一条：无（该文件条目已全部完成）")
                else:
                    lines.append("  - 下一条：无（未找到 checkbox 条目）")
            miss = int(it.get("done_missing_evidence") or 0)
            if miss:
                lines.append(f"  - 已完成但缺少证据字段（Impl/Module）：{miss} 条")
                for e in it.get("missing_evidence_examples") or []:
                    lines.append(f"    - {e['file']}:{e['line']} {e['text']}")

    if not report.get("scan_impl"):
        lines.append("")
        lines.append("提示：如需额外扫描实现线索（可选），加 `--scan-impl`。默认仅以 TODO 作为研发进度真源。")
        return "\n".join(lines) + "\n"

    lines.append("")
    if report.get("include_md"):
        lines.append("实现线索（包含 Markdown：结果更全，但会包含文档/设计稿的“意图”，不等于实现）：")
    else:
        lines.append("实现线索（默认排除 Markdown，避免被文档内容误导）：")

    modules = report.get("modules") or {}
    for module in requested_modules:
        payload = modules.get(module)
        if not payload:
            continue
        lines.append("")
        lines.append(f"[{module}]")
        signals = payload.get("signals") or {}
        for name, sdata in signals.items():
            cnt = int(sdata.get("count") or 0)
            status = "FOUND" if cnt > 0 else "MISS"
            lines.append(f"- {name}: {status} ({cnt})")
            ex = sdata.get("examples") or []
            for e in ex:
                lines.append(f"  - {e['file']}:{e['line']} {e['text']}")

        top_files = payload.get("top_files") or []
        if top_files:
            lines.append("- 推荐优先打开（信号密度高）：")
            for p in top_files[:8]:
                lines.append(f"  - {p}")

    lines.append("")
    lines.append("提示：如果当前仓库只有文档/配置，没有实现代码，可用 `--include-md` 先做“文档线索”扫描。")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "扫描仓库实现线索：用少量关键词信号快速判断当前实现到什么程度（默认排除 Markdown），"
            "并汇总 todo 进度（下一条 TODO/缺少 Impl+Module 证据的已完成条目）。"
        )
    )
    parser.add_argument("--root", default=".", help="扫描根目录（默认当前目录）")
    parser.add_argument(
        "--scan-impl",
        action="store_true",
        help="扫描实现线索（可选）。不加该参数时仅汇总 TODO 进度（推荐作为默认研发进度真源）。",
    )
    parser.add_argument(
        "--module",
        action="append",
        choices=MODULES + ["all"],
        default=["all"],
        help="指定模块（可重复）。默认 all。",
    )
    parser.add_argument(
        "--include-md",
        action="store_true",
        help="包含 Markdown（仅在 --scan-impl 时生效；会引入文档误匹配，谨慎使用）",
    )
    parser.add_argument("--max-file-bytes", type=int, default=2_000_000, help="单文件最大扫描字节数（默认 2MB）")
    parser.add_argument("--max-files", type=int, default=5000, help="最多扫描文件数（默认 5000）")
    parser.add_argument("--examples", type=int, default=5, help="每个信号最多输出多少条示例（默认 5）")
    parser.add_argument("--json", dest="json_out", action="store_true", help="输出 JSON（便于二次处理）")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    requested = set()
    for m in args.module:
        if m == "all":
            requested.update(MODULES)
        else:
            requested.add(m)

    started = time.time()
    if args.scan_impl:
        report = scan(
            root,
            include_md=bool(args.include_md),
            max_file_bytes=int(args.max_file_bytes),
            max_files=int(args.max_files),
            examples_limit=int(args.examples),
            requested_modules=requested,
        )
    else:
        report = {
            "root": root,
            "include_md": False,
            "scan_impl": False,
            "files_scanned": 0,
            "skipped_by_limit": 0,
            "todo_progress": parse_todo_progress(root),
            "stack_hints": detect_stack(root),
            "modules": {},
        }
    report["elapsed_ms"] = int((time.time() - started) * 1000)

    ordered_modules = [m for m in MODULES if m in requested]
    if args.json_out:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(report, requested_modules=ordered_modules))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
