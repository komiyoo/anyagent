# Output format (repo-symbol-trace)

本文件定义 `repo_symbol_trace.py` 的输出结构（对人可读 + 可机读）。

## 1) Markdown (`--format md`, 默认)

### 1.1 Header

- Target：目标符号（或从 file:line 推导的目标）
- Candidates：若歧义则列出候选（需 `--pick`）
- Stats：扫描文件数、defs 数、edges 数、cache 命中等

### 1.2 Node line

每个节点一行：

- `<qualname> (<path>:<line>) — <summary> [tags: a,b,c]`

其中：
- `summary`：优先 docstring 首行；缺失则为空
- `tags`：根据路径/目录启发式附加（例如 `agent-api`, `tool-runtime`, `protocol`, `storage`）

### 1.3 Callers paths

从“更可能是入口”的位置，走到目标：

- `root -> ... -> target`

### 1.4 Callees paths

从目标向下展开：

- `target -> ... -> leaf`

## 2) JSON (`--format json`)

顶层字段：

- `target`: `{ "qualname": str, "path": str, "line": int | null }`
- `candidates`: `[{ "qualname": str, "path": str, "line": int | null, "summary": str }]`
- `paths`:
  - `callers`: `list[list[str]]`（每条为 qualname 列表）
  - `callees`: `list[list[str]]`
- `nodes`: `dict[str, { "path": str, "line": int | null, "summary": str, "tags": list[str] }]`
- `unresolved_edges`: `list[{ "caller": str, "callee": str }]`
- `stats`: `{ "files": int, "defs": int, "edges": int, "cache": { "hit": bool, "path": str | null } }`

