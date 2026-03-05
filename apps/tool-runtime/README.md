# anyagent Tool Runtime（Python）

提供内部接口：

- `POST /internal/tools/manifest`
- `POST /internal/tools/execute`
- `POST /internal/tools/cancel`（best-effort）

## 启动

环境变量：

- `TOOL_RUNTIME_INTERNAL_KEY=...`（内部鉴权）
- `TOOL_RUNTIME_PLUGIN_ROOTS=/path/a,/path/b`（可选：插件根目录，逗号分隔）
- `ADMIN_API_KEY=...`（可选：启用凭证管理 Admin API）
- `HOST=127.0.0.1`（可选）
- `PORT=8788`（可选）
- `ALLOW_SANDBOX=false`（默认 false，sandbox.\* 默认 deny）

启动：

- `uv sync`
- `TOOL_RUNTIME_INTERNAL_KEY=... uv run tool-runtime`

## Demo 定制化能力

### 1) 插件扩展

- 通过 `TOOL_RUNTIME_PLUGIN_ROOTS` 指定插件根目录
- root 下任意包含 `plugin.json` 的目录会被识别为一个插件
- 插件可选 `config.json`，并按 `plugin.json.config_schema` 校验

### 2) 凭证管理（Admin API）

当设置 `ADMIN_API_KEY` 后，可通过：

- `POST /admin/credentials`
- `GET /admin/credentials`
- `DELETE /admin/credentials/{credential_id}`

或用 CLI：

```bash
anyagent credential list --admin-url http://127.0.0.1:8788 --admin-key "$ADMIN_API_KEY"
```

### 3) 与 Agent API 联调

Tool Runtime 只暴露内部接口，通常由 Agent API 调用：

- Agent API 侧配置 `TOOL_RUNTIME_BASE_URL` + `TOOL_RUNTIME_INTERNAL_KEY`
- Agent API 会按 Agent Pack / skills / policy 计算请求上下文并调用 manifest/execute

完整联调与定制化步骤见：

- `docs/acceptance/acceptance-demo-customization.md`

## v0 强制约束（摘要）

- registry 单一真源：所有工具（含 core.\*）都必须走同一套注册路径。
- 禁止覆盖/替换同名工具。
- tool.name 与 tool.category 必须一致（core/app/sandbox/channel）。
- Tool Runtime manifest 允许为工具附加内部扩展字段（例如 `x-anyagent-kind: command`），用于 Agent API 的 stage events 派生；但这些字段不得转发到上游模型（由 Agent API 剥离）。
- sandbox.\* 默认 deny；且即使“内置在同进程”，也禁止主进程直接执行不受信任代码（必须通过隔离执行环境）。
