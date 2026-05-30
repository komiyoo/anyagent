# Tool Runtime TODO

对应需求:`requirements.md#req-6`

## 目标

- Tool Runtime contract 在进程内与 standalone 两种形态下保持等价,credential 注入与 policy 强制不绑定单一 runtime。

## 当前事实

- Core 实现:`packages/anyagent/src/anyagent/tool_runtime/`
- Server 端点:`packages/anyagent/src/anyagent/server/` 内 tool 相关 handler
- Credential 注入 & policy:`packages/anyagent/src/anyagent/server/security/`
- Plugin / connector contract:`packages/anyagent/src/anyagent/plugins/`

## 里程碑

- M1:standalone Tool Runtime 与进程内 runtime 通过同一份 manifest/execute contract test
- M2:Tool Runtime GA(管理面 + 观测 + credential 注入)
- M3:Plugin / Connector 公开 contract 与一组参考实现(Phase 4)

## 任务

### Phase 1.5 — Agentic Ecosystem Hardening

- [x] P0 Tool Deferred Loading:在 `ToolDefinition` 增加 `exposure: Literal["direct", "deferred", "hidden"]` 字段,`ToolRegistry.list_tools()` 只返回 direct 工具完整 schema(Req: `requirements.md#req-5-2`、`requirements.md#req-5-2-1`; Impl: `packages/anyagent/src/anyagent/tool_runtime/models.py:29`; Module: `anyagent.tool_runtime`)
- [x] P0 Tool Search 机制:新增 `ToolRegistry.search_tools(query: str)` 方法 + 注册 `core.tool_search` built-in tool 供 agent loop 按需发现 deferred 工具(Req: `requirements.md#req-5-2-1`; Impl: `packages/anyagent/src/anyagent/tool_runtime/registry.py:180`; Module: `anyagent.tool_runtime`)
- [x] P1 Plugin Manifest v1 统一:升级 `PluginManifest` model,一个 plugin 可同时声明 skills/ + mcp_servers/ + tools/ + middlewares/ + hooks/。`middlewares` 字段声明 middleware 类路径（如 `"my_plugin.middleware:AuditMiddleware"`），框架按 `agent.yaml` 中 `runtime.middlewares` 顺序加载。`hooks` 字段声明生命周期回调（`on_agent_start`、`on_agent_end`）。参考 Pi-mono Extension manifest + OpenClaw plugin manifest（精简）(Req: `requirements.md#req-6`、`requirements.md#req-5-2`; Impl: `packages/anyagent/src/anyagent/plugins/models.py:45`、`packages/anyagent/src/anyagent/agent_runtime/middleware.py:190`、`packages/anyagent/src/anyagent/plugins/hooks.py:55`、`packages/anyagent/src/anyagent/plugins/loader.py:169`、`packages/anyagent/src/anyagent/server/app.py:141`; Module: `anyagent.plugins`)
- [x] P1 MCP 工具 filter 与 sanitize:MCP server 注册的工具名自动 sanitize（`^[a-z0-9_.-]+$`）+ 支持 per-server tool filter 配置(Req: `requirements.md#req-5-2`; Impl: `packages/anyagent/src/anyagent/mcp/util.py:11`, `packages/anyagent/src/anyagent/mcp/server.py:155`, `packages/anyagent/src/anyagent/mcp/manager.py:145`, `packages/anyagent/src/anyagent/protocol/mcp.py:28`, `tests/unit/mcp/test_mcp_tool_sanitize.py:15`; Module: `anyagent.mcp`, `anyagent.protocol.mcp`)
- [x] P1 MCP 会话池:按 `(server_name, session_key)` 池化 stdio 连接,LRU 淘汰（默认 256）。stdio 走池化,HTTP/SSE 不池化。参考 DeerFlow `session_pool.py`(Req: `requirements.md#req-5-2`; Impl: `packages/anyagent/src/anyagent/mcp/session_pool.py:32`, `packages/anyagent/src/anyagent/mcp/manager.py:69`, `packages/anyagent/src/anyagent/mcp/manager.py:324`, `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:243`, `tests/unit/mcp/test_mcp_session_pool.py:55`; Module: `anyagent.mcp`)

### Phase 2 — Production Runtime Hardening

- [x] P0 整理 Tool Runtime contract 测试矩阵,覆盖 manifest、execute、credential 注入、policy 强制(Req: `requirements.md#req-6`; Impl: `tests/contract/test_tool_runtime_contract_matrix.py:115`; Module: `tool-runtime-contract`)
- [x] P0 standalone Tool Runtime 管理面与进程内 runtime 的等价性验收(Req: `requirements.md#req-6`; Impl: `tests/contract/test_tool_runtime_contract_matrix.py:147`; Module: `tool-runtime-contract`)
- [ ] P1 Plugin contract 公开化:定义 manifest schema、生命周期 hook 与 capability matrix(Req: `requirements.md#req-6`)
- [ ] P2 参考实现:至少一个内置 Plugin 与一个 Connector 走完 contract,作为后续生态接入样板(Req: `requirements.md#req-6`)

## 决策 & 争议点

- [ ] Plugin 与 Connector 是统一 contract 还是分层 contract

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2 / Phase 4
- `docs/architecture/tool-runtime/`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- Pi-mono Extension manifest: `pi-mono/packages/coding-agent/src/core/extensions/types.ts`
- OpenClaw Plugin manifest: `openclaw/src/plugins/manifest.ts`
- DeerFlow MCP session pool: `deer-flow/backend/packages/harness/deerflow/mcp/session_pool.py`
