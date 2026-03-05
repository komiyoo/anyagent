# anyagent Tool Runtime（Python）

提供内部接口：

- `POST /internal/tools/manifest`
- `POST /internal/tools/execute`
- `POST /internal/tools/cancel`（best-effort）

## 启动

环境变量：

- `TOOL_RUNTIME_INTERNAL_KEY=...`（内部鉴权）
- `HOST=127.0.0.1`（可选）
- `PORT=8788`（可选）
- `ALLOW_SANDBOX=false`（默认 false，sandbox.\* 默认 deny）

启动：

- `uv sync`
- `TOOL_RUNTIME_INTERNAL_KEY=... uv run tool-runtime`

## v0 强制约束（摘要）

- registry 单一真源：所有工具（含 core.\*）都必须走同一套注册路径。
- 禁止覆盖/替换同名工具。
- tool.name 与 tool.category 必须一致（core/app/sandbox/channel）。
- Tool Runtime manifest 允许为工具附加内部扩展字段（例如 `x-anyagent-kind: command`），用于 Agent API 的 stage events 派生；但这些字段不得转发到上游模型（由 Agent API 剥离）。
- sandbox.\* 默认 deny；且即使“内置在同进程”，也禁止主进程直接执行不受信任代码（必须通过隔离执行环境）。
