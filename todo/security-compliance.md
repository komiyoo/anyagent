# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 当前仓库已补回最小安全主路径：`SandboxPolicy` 协议、会话级 `local-unsafe` exec 沙箱、内存版 write-only Credential Admin API。

## 最近完成

- [x] P3 建立统一 observability 事件入口：新增 typed `ObservabilityEvent` / `ObservabilityEmitter` / logging + HTTP JSON sink，并将 credential audit 与 tool execute audit 迁移到统一事件 envelope，保留现有日志兼容面（Req: `requirements.md#req-8`，`requirements.md#req-5-13`；Impl: `packages/anyagent/src/anyagent/observability.py:1`，`packages/anyagent/src/anyagent/server/security/credential_store.py:1`，`packages/anyagent/src/anyagent/server/runtime.py:1`，`tests/unit/test_observability.py:1`；Module: `observability`）
- [x] P3 将 observability 事件模型上提到 protocol SSOT，并把 MCP 生命周期/工具发现/工具调用纳入统一事件面，避免长期散落裸 logger（Req: `requirements.md#req-8`，`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/observability.py:1`，`packages/anyagent/src/anyagent/mcp/manager.py:1`，`tests/unit/mcp/test_mcp_observability.py:1`；Module: `observability/mcp`）
- [x] P3 将 Agent API response 生命周期纳入统一 observability：外部 `/v1/responses` 现覆盖 request/replay/run_start/stream terminal/nonstream terminal 事件，payload 仅包含稳定关联键与状态，不写入用户输入（Req: `requirements.md#req-8`，`requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/server/app.py:88`，`tests/integration/server/test_event_pipeline.py:376`；Module: `observability/agent-api`）
- [x] P1 回补 sandbox 协议与 AgentSpec 对齐：`agent.yaml` 现可声明 `sandbox.mode`，并由服务端按 agent 生效（Req: `requirements.md#req-2-2`，`requirements.md#req-5`；Impl: `packages/anyagent/src/anyagent/protocol/sandbox.py:1`，`packages/anyagent/src/anyagent/agent_packs.py:53`；Module: `server/sandbox`）
- [x] P1 实现最小会话级 exec 沙箱：`exec` 以 `core` 命令工具注册，复用 `session_partition_key` 对应目录执行命令（Req: `requirements.md#req-5`；Impl: `packages/anyagent/src/anyagent/server/sandbox/exec_handler.py:12`，`packages/anyagent/src/anyagent/server/sandbox/manager.py:10`；Module: `server/sandbox`）
- [x] P2 回补会话工作区协议与 built-in reference lifecycle：`SandboxPolicy.filesystem`、`SessionWorkspaceRecord`、workspace lifecycle stage events 已进入 Core，`local-unsafe + session_hot_cold` 现支持本地 reference 的 `ensure/checkpoint/hibernate/restore` 闭环（Req: `requirements.md#req-5`，`requirements.md#req-5-5`，`requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/protocol/sandbox.py:1`，`packages/anyagent/src/anyagent/storage/models.py:1`，`packages/anyagent/src/anyagent/server/sandbox/workspace.py:1`，`packages/anyagent/src/anyagent/server/sandbox/manager.py:1`，`packages/anyagent/src/anyagent/protocol/stage_events.py:1`；Module: `server/sandbox`）
- [x] P1 实现内存版 Credential Admin API：仅支持 set/list/delete 引用，不回传明文 value（Req: `requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/server/security/credential_store.py:15`，`packages/anyagent/src/anyagent/server/app.py:110`；Module: `server/security`）
- [x] P1 收紧 exec 暴露面：仅在 `sandbox.mode != disabled` 且 agent 显式请求 `exec` 时披露；caller policy 不得放大暴露面，`opensandbox` 未实现时启动 fail-fast（Req: `requirements.md#req-5-10`；Impl: `packages/anyagent/src/anyagent/server/runtime.py:166`，`packages/anyagent/src/anyagent/server/app.py:78`；Module: `server/sandbox`）
- [x] P1 收敛运行态取消语义：cancel 请求会先把 run 标记为 `cancelled`，再 best-effort 中断后台 task，使事件流与 retrieve/cancel 终态可收敛（Req: `requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/server/events.py:36`，`packages/anyagent/src/anyagent/server/runs.py:1`，`packages/anyagent/src/anyagent/server/app.py:293`；Module: `agent-api`）

## 待处理

### v2 规划（暂不实现）

- [x] P2 [cross-repo] 在 `anyagent-apps` 落地 production Workspace Service 的外置状态层：PostgreSQL workspace metadata、Redis lease、对象存储快照、跨实例恢复与真实 `postgres + redis + s3` live smoke 已打通；联调中同时修复了 Core `RedisLeaseLock` 的 renew/release 位置参数 bug（Req: `requirements.md#req-5`，`requirements.md#req-5-5`；Impl: `../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/workspace_service.py:1`，`../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/workspace_persistence.py:1`，`../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/workspace_snapshots.py:1`，`../anyagent-apps/tests/acceptance/tool_runtime/acceptance_exec_workspace_production_backends_smoke.py:1`，`packages/anyagent/src/anyagent/storage/external/redis_lock.py:1`；Module: `tool-runtime`）
- [x] P2 [cross-repo] 用真实 OpenSandbox 服务完成 live acceptance：`tool-runtime` 的 `opensandbox` backend 已切到官方 Lifecycle API + execd proxy，mock e2e 与真实 live smoke 都已通过（Req: `requirements.md#req-5`，`requirements.md#req-5-5`；Impl: `../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/opensandbox_backend.py:1`，`../anyagent-apps/tests/acceptance/tool_runtime/acceptance_exec_opensandbox_cross_instance_smoke.py:1`，`../anyagent-apps/tests/acceptance/tool_runtime/acceptance_exec_opensandbox_live_smoke.py:1`，`../anyagent-apps/config/opensandbox.server.local.toml:1`，`../anyagent-apps/docker-compose.storage.yml:1`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 DatabaseBackend（PostgreSQL 加密列存储）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 VaultBackend（对接 HashiCorp Vault / AWS Secrets Manager）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 session 级临时凭据 scope（CredentialScope.level=session）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证轮转与过期机制（expires_at + rotate_before）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证审计日志持久化（写入审计表，支持合规审查）（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Module: `tool-runtime`）
