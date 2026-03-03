---
name: repo-symbol-trace
description: "Enhanced repo exploration for Python codebases: locate a symbol (file/class/function/method) and disclose its callers/callees call chains with per-node function summaries (docstring first line). Use when you need call graph, call chain, impact analysis, or to understand how a function/class is used."
---

# Repo Symbol Trace

用静态分析（Python AST）增强“代码搜索”，把 **符号定位 + callers/callees 调用链 + 功能披露** 固化为一条命令。

## Quick start

运行帮助：

- `python3 .codex/skills/repo-symbol-trace/scripts/repo_symbol_trace.py --help`

示例（本仓库）：

- `python3 .codex/skills/repo-symbol-trace/scripts/repo_symbol_trace.py --symbol run_tool_loop_nonstream --direction both --depth 3`
- `python3 .codex/skills/repo-symbol-trace/scripts/repo_symbol_trace.py --file apps/agent-api/src/anyagent_agent_api/app.py --line 252 --direction callers --depth 4`

## 输入方式

三种常见入口：

1) **按符号名**：
- `--symbol <name>`：例如 `run_tool_loop_nonstream`、`OpenAIResponsesModelProvider`、`Class.method`

2) **按“模块:符号”**：
- `--symbol <module:qualname>`：例如 `anyagent.agent_runtime.tool_loop:run_tool_loop_nonstream`

3) **按文件行号反推所属函数/方法**：
- `--file <path> --line <N>`：当你手里只有堆栈或 grep 结果行号时用

额外：当符号同名较多时，可以用 `--file <path>` 作为过滤条件（无需 `--line`）。

如果符号存在歧义（同名多处定义），脚本会输出候选列表；此时追加 `--pick <index>` 选择（从 1 开始）。

## 输出（默认 Markdown）

默认 `--format md`，每个节点输出：

- `qualname (path:line) — <docstring 首行或空> [tags: ...]`

并给出：
- callers 路径（从入口趋近到目标）
- callees 路径（从目标向下展开）

更结构化的场景可用 `--format json`（便于后续接 UI/Agent）。

详细字段见：`references/output-format.md`。

## 约束与降级

- 只做静态分析，不会执行仓库代码。
- 语言范围：Python AST（首版）；其他语言暂不做精确调用图。
- 动态特性（反射/动态导入/运行时绑定）可能无法完全解析：脚本会标记为 `unresolved`，但仍展示为链路叶子节点。

## 常用排障套路（推荐）

1) 先找入口（callers）：
- `--direction callers --depth 4`

2) 再看依赖（callees）理解实现面：
- `--direction callees --depth 3`

3) 影响分析（谁会被改动波及）：
- `--direction callers --depth 5 --max-paths 50`
