# Tool Runtime TODO

对应需求：`requirements.md#req-5`

## 目标

- 提供统一的工具清单（manifest）与执行入口（execute），并实现策略/幂等/取消/审计的核心语义。

## 里程碑（Milestones）

- M1：`manifest` 与 `execute` 契约稳定，能跑通 core 工具
- M2：加入 sandbox/channel 分类与策略校验
- M3：幂等/取消/可观测/审计齐备

## 任务（Tasks）

- [x] P0 定义并实现 Tool Execute API（Agent API -> Tool Runtime）（Req: `requirements.md#req-5-1`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:141`；Module: `tool-runtime`）
- [x] P0 定义并实现 Tool Manifest API（Tool Runtime -> Agent API）（Req: `requirements.md#req-5-2`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:78`；Module: `tool-runtime`）
- [x] P0 安全：`requested_tool_names=[]` 必须返回空 tools（避免空列表退化为全量工具可见）（Req: `requirements.md#req-5-2`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/manifest.py:39`；Module: `tool-runtime`）
- [x] P0 落地工具命名规范与保留名前缀/命名空间约束（Req: `requirements.md#req-5-6`；Impl: `packages/anyagent/src/anyagent/tool_runtime/registry.py:33`；Module: `tool-runtime`）
- [x] P1 落地 Tool Definition 统一约定（对齐 `/v1/responses` tools[]）（Req: `requirements.md#req-5-7`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/manifest.py:12`；Module: `tool-runtime`）
- [x] P1 实现 `/internal/tools/execute` 字段级契约校验（Req: `requirements.md#req-5-8`，`requirements.md#req-5-8-1`，`requirements.md#req-5-8-2`；Impl: `packages/anyagent/src/anyagent/protocol/tool_runtime.py:86`, `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:296`, `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:19`；Module: `tool-runtime/protocol`）
- [x] P1 定义并实现标准化 `context` 结构（平台无关 + 平台扩展）（Req: `requirements.md#req-5-9`；Impl: `packages/anyagent/src/anyagent/protocol/tool_runtime.py:40`；Module: `protocol`）
- [x] P1 实现工具权限与策略（policy）判定（Req: `requirements.md#req-5-10`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/policy.py:13`, `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:19`, `apps/tool-runtime/src/anyagent_tool_runtime/runtime/manifest.py:39`；Module: `tool-runtime`）
- [x] P1 实现幂等去重（idempotency/dedupe）语义（Req: `requirements.md#req-5-11`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/idempotency.py:16`, `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:141`；Module: `tool-runtime`）
- [x] P1 实现取消（abort）传播与执行终止语义（Req: `requirements.md#req-5-12`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:281`, `apps/tool-runtime/src/anyagent_tool_runtime/runtime/idempotency.py:39`；Module: `tool-runtime`）
- [x] P2 实现可观测性与审计事件（Req: `requirements.md#req-5-13`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:55`；Module: `tool-runtime`）
- [x] P1 收敛 Tool Runtime HTTP 协议模型：移除 app 内重复定义，统一复用 `anyagent.protocol.tool_runtime`（Req: `requirements.md#req-5-8`，`requirements.md#req-5-9`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/api_models.py:1`；Module: `tool-runtime/protocol`）

## 决策 & 争议点

- [x] Tool Registry 热更新控制面：v0 不做 `/internal/tools/register|heartbeat`，采用启动期静态注册 + mismatch 刷新恢复（Req: `requirements.md#req-5-2-1`；Impl: `docs/architecture/decisions/tool-runtime-federation-v0.md:1`；Module: `architecture/tool-runtime`）
- [x] “联邦式 Tool Runtime” 边界：v0 固化单服务部署（router + executors 同进程），不拆 remote executors（Req: `requirements.md#req-5-3`；Impl: `docs/architecture/decisions/tool-runtime-federation-v0.md:1`；Module: `architecture/tool-runtime`）

## Credential Vault 集成（v1）

对应设计：`docs/security/credential-vault.md`

- [x] P0 扩展 ToolDefinition：新增 `credentials: list[ToolCredentialSpec]` 字段（Req: `requirements.md#req-5-9`，`requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/tool_runtime/models.py:12`；Module: `packages/anyagent`）
- [x] P0 实现 CredentialStore 抽象与 EnvBackend 默认后端（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/credential_store.py:16`；Module: `tool-runtime`）
- [x] P0 Router.execute() 增加凭证 resolve + 注入逻辑（在 policy 校验后、handler 执行前）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:204`；Module: `tool-runtime`）
- [x] P1 实现 Admin API endpoints（POST/GET/DELETE /admin/credentials，独立 ADMIN_API_KEY）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:103`；Module: `tool-runtime`）
- [x] P1 实现 FileBackend 凭证存储（文件系统 + chmod 600）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/file_credential_store.py:27`；Module: `tool-runtime`）
- [ ] P1 改造 core.web_fetch：支持从 `_credentials` 获取认证头（适用于需要鉴权的 URL 访问）（Req: `requirements.md#req-5-9`；Module: `tool-runtime`）
- [ ] P2 实现 core.web_search 内置工具（从 CredentialStore resolve 搜索引擎 API Key）（Req: `requirements.md#req-5-10`；Module: `tool-runtime`）

## 参考

- `requirements.md`
- `docs/security/credential-vault.md`
