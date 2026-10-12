# Tool Runtime TODO

对应需求:`requirements.md#req-6`、`requirements.md#req-0-2`

## 目标

- Tool Runtime contract 在进程内与 standalone 两种形态下保持等价,credential 注入与 policy 强制不绑定单一 runtime。

## 当前事实

- Core 实现:`packages/anyagent/src/anyagent/tool_runtime/`
- Server 端点:`packages/anyagent/src/anyagent/server/` 内 tool 相关 handler
- Credential 注入 & policy:`packages/anyagent/src/anyagent/server/security/`
- Plugin / connector contract:`packages/anyagent/src/anyagent/plugins/`

## 当前状态

- Phase 1.5 / Phase 2 的 Tool Runtime 任务已全部完成;已完成条目已清理,历史记录请查看 Git。
- CLI Profile（`tools.cli`）主路径已完成并进入当前长期口径:
  - Req: `requirements.md#req-6`
  - Impl: `packages/anyagent/src/anyagent/tool_runtime/cli_profile.py`
  - Impl: `packages/anyagent/src/anyagent/tool_runtime/cli_env.py`
  - Impl: `packages/anyagent/src/anyagent/server/runtime/in_process.py`
  - Module: `tests/unit/tool_runtime/test_cli_profile.py`
  - Module: `tests/acceptance/server/acceptance_cli_profile_smoke.py`
- 已实现能力的长期口径见架构文档:
  - Tool Runtime manifest/execute、registry、exposure 分级(direct/deferred/hidden)与 `core.tool_search` 按需发现:`docs/architecture/tool-runtime/tool-runtime-contract.md`
  - MCP 工具 sanitize/filter、会话池与生命周期事件:`docs/architecture/runtime/agent-packs-and-runtime-config.md`
  - Plugin / Connector 公开 contract:`docs/architecture/integrations/platform-connectors.md`、`docs/architecture/decisions/plugin-connector-contract-v1.md`

## 里程碑

- M1:standalone Tool Runtime 与进程内 runtime 通过同一份 manifest/execute contract test ✅
- M2:Tool Runtime GA(管理面 + 观测 + credential 注入)✅
- M3:Plugin / Connector 公开 contract 与一组参考实现 ✅

## 已完成任务（0.5 随包插件）

- [x] 随包插件 `chatwoot` 与 `lifecycle_echo` 经 `plugins.builtin` 显式启用。省略或空列表时两者都不加载。（Req: `requirements.md#req-0-2`、`requirements.md#req-6`；Impl: `packages/anyagent/src/anyagent/server/app_builders.py:141`、`packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.json:3`、`packages/anyagent/src/anyagent/plugins/builtin/lifecycle_echo/plugin.json:3`；Module: `anyagent.server.app_builders`）

## 待处理

- 本模块当前无未完成任务。Credential v2(Phase 3)见 `todo/security-compliance.md`。

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2 / Phase 4
- `docs/architecture/tool-runtime/`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- Pi-mono Extension manifest: `pi-mono/packages/coding-agent/src/core/extensions/types.ts`
- OpenClaw Plugin manifest: `openclaw/src/plugins/manifest.ts`
- DeerFlow MCP session pool: `deer-flow/backend/packages/harness/deerflow/mcp/session_pool.py`
