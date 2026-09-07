# Studio 控制面后端 API TODO

对应需求：`requirements.md#req-14`

## 目标

- 补齐 Studio 与 SDK 控制台消费的 server typed API，覆盖运营态查询面、配置面破洞、运维面盲区、合规查询面、质量闭环后端、Prompt 版本管理与主动监控。
- 所有端点遵循 §0.3 协议治理：先回 `anyagent.protocol.*` 定义 wire model，再落 server handler，最后 Studio/SDK 消费。

## 背景

Studio 控制面前端（16 页）骨架已落地并消费现有 typed API，但从后端能力域看，运营态/治理态整片缺失。本文件登记 6 个后端缺口对应的实现任务。能力边界与页面归属见 `docs/architecture/control-plane/studio-control-plane-and-observability.md`。

## 当前事实

- Server 入口：`packages/anyagent/src/anyagent/server/app.py`
- 已落地端点：`/v1/responses`(+get/cancel)、`/internal/agents`、`/internal/tools/*`、`/internal/skills/list`、`/internal/observability/{summary,runs,timeline,metrics,tools,errors,traces}`、`/internal/responses/{id}/{prompt-context,tool-executions,model-request}`、`/internal/events/{list,stream}`、`/admin/credentials*`、`/admin/workspace/agents*`、`/admin/plugins/*`、`/admin/storage/health`
- Stage events（已发但缺查询/告警面）：`anyagent.mcp.server.{starting,ready,failed}`、`anyagent.sandbox.workspace.*`、`anyagent.agent.{loop_warning,loop_terminated}`（`packages/anyagent/src/anyagent/protocol/stage_events.py`）
- Telemetry / observability 真源：`anyagent.protocol.observability`、`packages/anyagent/src/anyagent/server/telemetry_store.py`

## 里程碑（Milestones）

- M1：查询面缺失补齐（Sessions / MCP 管理 / Sandbox 运维 / Audit）——数据已存在，开聚合查询出口
- M2：主动监控（Alert）——alert rule 存储 + 后台评估器 + 订阅端点 + webhook fan-out
- M3：质量闭环与版本管理（Evaluations/Dataset、Prompt 版本）——新增持久化模型 + 业务逻辑

## 任务（Tasks）

### M1 — 查询面缺失（数据已存在，开查询出口）

- [x] P1 Sessions 编排查询面：新增 `GET /internal/sessions`（按 agent/session_key 过滤、分页）与 `GET /internal/sessions/{key}`（会话详情 + run 列表 + 会话级聚合），protocol 侧定义 SessionSummary / SessionDetail wire model（Req: `requirements.md#req-14-1`；Impl: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:252`, `packages/anyagent/src/anyagent/server/routes/internal_observability.py:28`, `packages/anyagent/src/anyagent/agent_api_client.py:603`；Module: `anyagent.protocol.agent_api_internal`, `anyagent.server.routes.internal_observability`, `anyagent.agent_api_client`）
- [x] P1 MCP 管理 API：新增 `GET /admin/workspace/agents/{id}/mcp/servers`（结构化列表 + enablement 摘要：enabled/disabled/inherited/invalid）、单 server enable/disable、连接测试端点，消费 `anyagent.mcp.server.*` lifecycle event 暴露运行态（Req: `requirements.md#req-14-2`；Impl: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:678`, `packages/anyagent/src/anyagent/server/routes/admin.py:357`, `packages/anyagent/src/anyagent/mcp/manager.py:279`, `packages/anyagent/src/anyagent/agent_api_client.py:1011`；Module: `anyagent.protocol.agent_api_internal`, `anyagent.server.routes.admin`, `anyagent.mcp.manager`, `anyagent.agent_api_client`）
- [x] P2 Sandbox / Workspace 运维 API：新增 `GET /admin/sandboxes`（活跃 sandbox 列表）、`GET .../workspaces/{id}/snapshots`（快照列表）与强制回收/reclaim 端点，消费 `AnyAgentWorkspaceLifecycleEvent`（Req: `requirements.md#req-14-3`；Impl: `packages/anyagent/src/anyagent/protocol/admin_storage.py:108`, `packages/anyagent/src/anyagent/server/routes/admin.py:187`, `packages/anyagent/src/anyagent/server/sandbox/manager.py:93`, `packages/anyagent/src/anyagent/agent_api_client.py:971`；Module: `anyagent.protocol.admin_storage`, `anyagent.server.routes.admin`, `anyagent.server.sandbox.manager`, `anyagent.agent_api_client`）
- [x] P2 Audit 独立查询面：新增独立 audit 查询端点，支持按 `credential_id` / `agent_id` / 时间窗过滤，与 `/internal/observability/errors` 解耦（Req: `requirements.md#req-14-4`；Impl: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:402`, `packages/anyagent/src/anyagent/server/persistence/telemetry_store.py:496`, `packages/anyagent/src/anyagent/server/routes/internal_observability.py:291`, `packages/anyagent/src/anyagent/agent_api_client.py:638`；Module: `anyagent.protocol.agent_api_internal`, `anyagent.server.persistence.telemetry_store`, `anyagent.server.routes.internal_observability`, `anyagent.agent_api_client`）

### M2 — 主动监控（新运行时机制）

- [x] P1 Alert 后端：protocol 定义 alert rule 模型，新增 alert rule 存储 + 后台评估器 + `GET /internal/observability/alerts` 订阅/查询端点 + webhook fan-out；优先消费 `loop_warning` / `loop_terminated` 与 error rate / latency 阈值（Req: `requirements.md#req-14-7`；Impl: `packages/anyagent/src/anyagent/protocol/alerts.py:23`, `packages/anyagent/src/anyagent/server/persistence/alerts.py:86`, `packages/anyagent/src/anyagent/server/routes/internal_observability.py:257`, `packages/anyagent/src/anyagent/agent_api_client.py:577`；Module: `anyagent.protocol.alerts`, `anyagent.server.persistence.alerts`, `anyagent.server.routes.internal_observability`, `anyagent.agent_api_client`）

### M3 — 质量闭环与版本管理（新存储 + 逻辑）

- [x] P2 Evaluations / Dataset 后端：dataset 持久化存储（CRUD）、`POST /internal/evaluations/run` 评测执行器、结果存储与查询；替换 Studio 当前 localStorage-only 形态（Req: `requirements.md#req-14-5`；Impl: `packages/anyagent/src/anyagent/protocol/evaluations.py:22`, `packages/anyagent/src/anyagent/server/persistence/evaluations.py:13`, `packages/anyagent/src/anyagent/server/routes/internal_evaluations.py:74`, `packages/anyagent/src/anyagent/agent_api_client.py:645`；Module: `anyagent.protocol.evaluations`, `anyagent.server.persistence.evaluations`, `anyagent.server.routes.internal_evaluations`, `anyagent.agent_api_client`）
- [x] P3 Prompt 版本管理后端：prompt 版本快照存储 + `GET .../prompt/versions` + 版本 diff + admin-gated restore，与三类 replay 互补（Req: `requirements.md#req-14-6`；Impl: `packages/anyagent/src/anyagent/protocol/prompt_versions.py:21`, `packages/anyagent/src/anyagent/server/persistence/prompt_versions.py:11`, `packages/anyagent/src/anyagent/server/routes/internal_prompt.py:140`, `packages/anyagent/src/anyagent/server/routes/internal_prompt.py:210`, `packages/anyagent/src/anyagent/agent_api_client.py:954`；Module: `anyagent.protocol.prompt_versions`, `anyagent.server.persistence.prompt_versions`, `anyagent.server.routes.internal_prompt`, `anyagent.agent_api_client`）

完成时在同一行补齐证据字段：

- `[x] ...（Req: ...；Impl: <path:line>；Module: <module>）`

## 决策 & 争议点

- [x] Evaluations/Dataset 与 Prompt 版本存储后端：v0 采用 workspace-local JSON reference store，文件为 `.anyagent/evaluations.json` 与 `.anyagent/prompt_versions.json`（关联：`requirements.md#req-14-5`、`requirements.md#req-14-6`、`requirements.md#req-3-1`；Impl: `packages/anyagent/src/anyagent/server/persistence/evaluations.py:13`, `packages/anyagent/src/anyagent/server/persistence/prompt_versions.py:11`；Module: `anyagent.server.persistence.evaluations`, `anyagent.server.persistence.prompt_versions`）
- [x] Alert fan-out 的最小集：v0 仅 webhook，后续 PagerDuty/IM 渠道作为 `AlertChannel` adapter 扩展（关联：`requirements.md#req-14-7`；Impl: `packages/anyagent/src/anyagent/protocol/alerts.py:16`, `packages/anyagent/src/anyagent/server/persistence/alerts.py:145`；Module: `anyagent.protocol.alerts`, `anyagent.server.persistence.alerts`）
- [x] 错误捕获 → webhook 通知：alert evaluator 按 `rule.event_types` 通用匹配（去硬编码）；新增 `builtin.server_error` 默认规则覆盖 `server.response.*.failed` / `chatwoot.background.failed` / `server.unhandled_exception`；`AlertChannel.format` 支持 `json` | `feishu`（纯文本摘要）；启动期从 `ALERT_WEBHOOK_URL` / `ALERT_WEBHOOK_FORMAT` / `ALERT_WEBHOOK_HEADERS` 注入 webhook channel。同步修正 429/4xx 归级为 error + run finalize 为 failed（不再停留 in_progress）、全局未捕获异常兜底 emit `server.unhandled_exception`、chatwoot 失败路径 emit `chatwoot.background.failed`、platform event 落库失败不再静默丢弃（emit `chatwoot.platform_event.persist_failed`）、SQL 后端 platform event auto-create run 不再抛 run_not_found（关联：`requirements.md#req-14-7`；Impl: `packages/anyagent/src/anyagent/server/persistence/alerts.py:21`, `packages/anyagent/src/anyagent/server/app.py:162`, `packages/anyagent/src/anyagent/server/routes/responses.py:796`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py:114`, `packages/anyagent/src/anyagent/storage/external/sqlalchemy_backend.py:345`；Module: `anyagent.server.persistence.alerts`, `anyagent.server.app`, `anyagent.server.routes.responses`, `anyagent.plugins.builtin.chatwoot_connector`, `anyagent.storage.external.sqlalchemy_backend`）
- [x] M3 是否独立立项：本轮完成 reference 后端；更复杂打分器、跨实例数据库表与 Studio 深度联调可后续独立立项（关联：`requirements.md#req-14-5`）

## 参考

- `requirements.md#req-14`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
- `docs/architecture/overview/system-components.md` — 控制面/执行面/隔离面/状态面组件边界
- `docs/architecture/overview/roadmap.md` Phase 2.5
- `docs/security/audit-logging.md`
- `packages/anyagent/src/anyagent/protocol/stage_events.py`
- `packages/anyagent/src/anyagent/server/app.py`
