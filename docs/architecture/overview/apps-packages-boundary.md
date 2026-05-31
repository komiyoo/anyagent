<!--
---
doc_kind: architecture
status: stable
tags: ["boundary", "anyagent", "anyagent-apps", "server-core", "security"]
summary: anyagent (框架本体) 与 anyagent-apps (示例与模板) 的职责边界与安全模型。
---
-->

# anyagent / anyagent-apps 职责边界

## 1. 总体定位

```text
┌─────────────────────────────────────────────────────────┐
│                anyagent (框架本体)                       │
│                                                          │
│  Server Core + SDK + production runtime + ops            │
│  轻量默认安装，生产能力通过 extras / 插件 / 子命令启用       │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │protocol.*│ │agent_    │ │ skills.* │ │   mcp.*   │  │
│  │(协议SSOT)│ │runtime.* │ │(发现/选择)│ │(MCP管理)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────────┐   │
│  │gateway.* │ │tool_     │ │  server/ (内置)        │   │
│  │(会话/路由)│ │runtime.* │ │  ├─ Agent API         │   │
│  └──────────┘ │(工具注册)│ │  ├─ Tool Runtime      │   │
│               └──────────┘ │  ├─ reference store   │   │
│  ┌──────────────────────┐  │  └─ security/         │   │
│  │ storage.* / plugins.*│  └───────────────────────┘   │
│  └──────────────────────┘                               │
│  ┌──────────────────────┐                               │
│  │ AnyAgent Client SDK  │                               │
│  └──────────────────────┘                               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│            anyagent-apps (示例与模板)                    │
│                                                          │
│  展示如何用 anyagent 构建具体业务 agent 应用               │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │ 业务示例与模板                                  │      │
│  │ ├─ demo-workspace                              │      │
│  │ ├─ trip-planner-workspace                      │      │
│  │ ├─ inbound-tour-sales-workspace                │      │
│  │ └─ templates/*                                 │      │
│  └───────────────────────────────────────────────┘      │
│  ┌───────────────────┐  ┌────────────────────────┐      │
│  │ 示例验收           │  │ 示例平台接线           │      │
│  │ ├─ demo-workspace │  │ ├─ plugins/feishu      │      │
│  │ ├─ multi-agent    │  │ ├─ plugins/discord     │      │
│  │ └─ project-tpl    │  │ └─ plugins/slack       │      │
│  └───────────────────┘  └────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

## 2. 职责划分

### anyagent — Server Core + SDK

**拥有（Owns）**：

| 模块 | 职责 | 路径 |
|---|---|---|
| `protocol.*` | Wire-level 协议 SSOT（Responses/Tool Runtime/SSE/Multi-Agent/Stage Events） | `packages/anyagent/src/anyagent/protocol/` |
| `agent_runtime.*` | Agent loop 运行时（model providers、tool loop、prompt 注入、session runtime） | `packages/anyagent/src/anyagent/agent_runtime/` |
| `skills.*` | Skills 发现/加载/选择/权限/注入 | `packages/anyagent/src/anyagent/skills/` |
| `mcp.*` | MCP server 管理（auth、连接池、工具发现） | `packages/anyagent/src/anyagent/mcp/` |
| `gateway.*` | 会话映射、agent 路由、sequencer | `packages/anyagent/src/anyagent/gateway/` |
| `tool_runtime.*` | 工具注册、HTTP client、standalone server、plugin 模型 | `packages/anyagent/src/anyagent/tool_runtime/` |
| `agent_packs` | Agent Packs 配置加载与校验 | `packages/anyagent/src/anyagent/agent_packs.py` |
| `storage.*` | 共享存储模型、contracts、runtime bundle、replay helper、capability matrix、SQL/Redis/MySQL reference adapters、schema/migration helper、retention/replay 运维语义 | `packages/anyagent/src/anyagent/storage/` |
| `plugins.*` | Core 侧插件 API、loader 与插件模型 | `packages/anyagent/src/anyagent/plugins/` |
| `server/` | **内置 Agent Server + 共享 Agent API 服务层 + production runtime shell**（FastAPI + reference/external store glue + resume/replay/orchestration 语义） | `packages/anyagent/src/anyagent/server/` |
| `AnyAgent` SDK | Client SDK 资源型命名空间（openai/responses/events/skills/tools/admin） | `packages/anyagent/src/anyagent/agent_api_client.py` |
| CLI | `anyagent serve` / `tool-runtime serve` / `init` / `doctor` / `storage-health` / `storage-migrate` / `storage retention` / `storage replay` 等框架级入口 | `packages/anyagent/src/anyagent/cli.py` |
| Security | Credential Vault / Tool Policy / Agent Sandbox 策略定义 | `packages/anyagent/src/anyagent/server/security/` |

**不做**：

- 不把默认安装路径变成重依赖包；PG/MySQL/Redis、Studio、平台 connector 通过 extras、插件或子命令按需启用
- 不把业务 workspace、示例 skill、示例 agent 配置上提为框架默认行为
- 不做具体平台 Gateway 的业务接线配置
- 不做 K8s/Helm 部署编排

### anyagent-apps — 示例与模板

**拥有（Owns）**：

| 模块 | 职责 | 路径 |
|---|---|---|
| 示例 workspace | demo-workspace、trip-planner、inbound-tour-sales、travel-agents 等业务 agent 配置 | `examples/` |
| 模板 | basic-agent、multi-agent-team、platform-bot 等业务项目脚手架 | `templates/` |
| 示例平台接线 | 如何使用官方插件、CLI 或 connector contract 接入平台，不拥有平台 contract 真源 | `plugins/` / `docs/` |
| 示例验收 | examples/templates 如何 against installed/published `anyagent` 启动和验收 | `tests/acceptance/` / `docs/acceptance/` |

**不做**：

- 不重复实现协议模型（必须复用 `anyagent.protocol.*`）
- 不重复实现 agent loop 核心（必须复用 `anyagent.agent_runtime.*`）
- 不自定义 SDK client（必须使用 `AnyAgent`）
- 不拥有 PG/MySQL/Redis storage contract、分布式锁 contract、Tool Runtime protocol/client/server contract、Credential/Connector contract 或 ops CLI 真源

## 3. 收敛策略（Protocol-First + Shared-Service-First）

1. 新增/修改任何协议（HTTP payload / SSE event / internal model）→ 先更新 `anyagent.protocol.*`
2. `Session/Run/Event/Dedupe/Lock` 的抽象模型、replay contract、resume 语义、共享 orchestration service 应优先收敛到 `anyagent`
3. `anyagent.server/` 是内置 server 的参考实现，也应逐步成为 built-in server 与分布式 Agent API 的共享服务层
4. PG/MySQL/Redis backend contract、分布式锁、Tool Runtime protocol/client/server、Credential/Connector contract 与 ops CLI 属于框架生产能力，默认进入 `anyagent`
5. `anyagent-apps` 只保留消费示例、模板和验收脚本；不保留 `apps/agent-api` / `apps/tool-runtime` / `apps/studio` 兼容兜底

### 3.1 当前收敛方向

当前推荐的收敛口径是：

- `anyagent` 拥有共享语义、公共服务层、production runtime contract 与 ops 入口
- `anyagent-apps` 拥有 examples/templates、示例 connector 接线和消费侧验收

具体来说：

- 应逐步回收到 `anyagent` 的部分：
  - store interfaces 与核心状态模型
  - Session Resume / runtime config merge 语义
  - internal events / replay / `last_seq` / `[DONE]` 契约
  - built-in server 与 distributed Agent API 共用的 request normalization / response assembly / orchestration service
- 继续留在 `anyagent-apps` 的部分：
  - examples/templates 的业务配置、运行说明与验收入口
  - 示例 connector / 官方 CLI 使用说明
  - 消费侧验收脚本和文档，验证业务示例可通过已发布 SDK/CLI 运行

当前已落地的第一步实现与迁移依据：

- `anyagent.storage.models` 已成为 `RunRecord` / `EventRecord` / `SessionRecord` / `LeaseLockHandle` 的共享真源
- `anyagent.storage.contracts` 已成为分布式 `agent-api` storage contracts 的共享真源
- `anyagent.storage.runtime.StorageRuntime` 与 `create_storage_runtime` 已成为 Core storage runtime bundle / assembly 的共享真源；apps Agent API 侧历史 `storage.runtime` wrapper 已删除，不再保留重复实现
- `anyagent.server.request_context` 已成为 Agent API `agent_id` / `session_key` 入口解析的共享真源，Core built-in server 与迁移期 apps service shell 共用同一语义；其中 `prepare_responses_request_context` 已承载分布式 `/v1/responses` 的 agent lookup/exposed 校验、默认 model 填充、ephemeral session、session partition、thread metadata 与 Idempotency-Key 规范化。
- `anyagent.server.response_tooling.prepare_response_tooling_context` 已承载分布式 Agent API `/v1/responses` 执行前的 tooling service 层，包括 skills 选择、server-generated ToolContext policy、manifest cache/fetch、MCP/system tools 合并、tool_choice 校验、manifest 内部字段剥离与 prompt envelope/audit 生成；分布式模型执行/streaming 编排也已收敛到 Core `response_execution` / `response_persistence` / `distributed_responses`。
- `anyagent.server.idempotency.begin_distributed_response_run` 已开始承载分布式 Agent API `/v1/responses` 的 idempotency started-run gate、session mismatch 冲突响应、stream replay、nonstream replay/等待与 in-progress timeout；迁移期 apps Agent API 直接消费 Core helper，减少 route 内 storage replay glue。
- `anyagent.server.session_serialization` 已开始承载分布式 Agent API `/v1/responses` 的本地 keyed serialization、external storage lease acquire/renew/release、busy response 与 idempotent stream leader lease skip 语义；迁移期 apps Agent API 直接消费 Core helper，减少 route 内 session concurrency glue。
- `anyagent.server.response_execution` 已开始承载分布式 Agent API `/v1/responses` 的 nonstream 与 streaming 执行编排，包括 nonstream tool loop 调用、forward stream 错误 SSE 转换、idempotent stream leader 后台持久化、成功/失败 run finalization 与非幂等 session advance；`anyagent.server.response_persistence` 已开始承载 Event Store 写入、stage event 编码、prompt-context event、run final + session persistence 与 session-only advance 回调组装；迁移期 apps Agent API 直接消费 Core helper。
- `anyagent.server.distributed_runtime` 已开始承载分布式 Agent API runtime/lifespan 装配，包括 shared http client、Tool Runtime client、MCP registry/credential resolver、model provider、multi-agent manager、manifest cache、storage runtime 注入、agent catalog 校验、skills discovery、storage task set 与 cleanup。
- `anyagent.server.distributed_responses.create_distributed_responses_router` 已开始承载分布式 Agent API `/v1/responses` router factory，把鉴权、请求规范化、幂等 gate、session context、tooling context、persistence callbacks、stream/nonstream execution 与 session serialization 串联在 Core；迁移期 apps Agent API 先前只挂载该 Core router，但现在该 Python 包本身已删去运行入口和 router 壳子。
- `anyagent.server.distributed_app.create_distributed_agent_app` 已开始承载分布式 Agent API 的 FastAPI service shell，包括 lifespan/runtime attach/cleanup、health/ready、`/v1/responses`、optional responses、internal events 与 internal skills router 挂载；迁移期 apps Agent API 先前的 `create_app(Settings())` 适配层已删除，现仅保留历史包名与说明痕迹。
- Core CLI 已提供 `anyagent agent-api serve` 作为分布式 Agent API 启动入口，复用 `create_distributed_agent_app`、Core `StorageSettings` / `create_storage_runtime` 与历史 `AGENT_API_KEY`、`TOOL_RUNTIME_BASE_URL`、`TOOL_RUNTIME_INTERNAL_KEY`、`STORAGE_MODE` 等 env 约定；apps `scripts/dev/start_services.sh --mode agent-api|stack` 调用已安装或已发布的 Core CLI。
- `anyagent-apps` 的 Agent API acceptance 已改为通过 `tests/acceptance/agent_api/_core_app.py` 直接构建 Core distributed app；request validation、optional responses、manifest cache、prompt-context replay summary、skills disabled-paths、session resume 与 storage smokes 不再 import apps `anyagent_agent_api.app` / `Settings` / `storage.runtime` wrapper。历史 `anyagent-apps/apps/agent-api` 服务壳已删除，不能作为兼容入口恢复。
- `apps/agent-api` 已删除；旧 OpenAI proxy/client helper、`agent-api` console script、`clients/` 目录、迁移期 multiagent package、`main.py` / `__main__.py` / `settings.py` / `storage/runtime.py` / `storage/__init__.py` / `app.py` 均不再保留兜底，runtime 真源完全在 Core。
- `anyagent.tool_runtime.client` 已成为 Tool Runtime HTTP client、manifest helper 与 execute helper 的共享真源；迁移期 apps Agent API 已直接消费 Core client，不再保留历史 bridge re-export。
- `anyagent.tool_runtime.server.create_tool_runtime_app` 与 `anyagent tool-runtime serve` 已提供 Core standalone Tool Runtime 的最小服务形态，复用 `anyagent.protocol.tool_runtime`、`anyagent.protocol.admin_storage` 与 `anyagent.server.runtime.InProcessToolRuntimeService`；当前覆盖 manifest / execute / cancel / list、admin credential API、credential capability matrix、plugin loading、`/admin/plugins/catalog` 可追溯目录、本地 reference sandbox workspace 的 health/list/get/hibernate/delete 控制面闭环，以及 `anyagent.server.sandbox.workspace_events` 支撑的 `/admin/sandbox/events` 内存/jsonl lifecycle event store。`anyagent.tool_runtime.builtin_tools` 已成为 `core.web_fetch`、`core.web_search` 与 privileged `admin.credential_set` 的注册真源，Core in-process / standalone runtime 默认注册内置工具，并统一使用 `ToolDefinition.credentials` 解析到 handler context `_credentials` 的 credential 注入路径。`anyagent.server.runtime.InProcessToolRuntimeService` 已向 handler context 透传 `_trace_id` / `_audit_ref`，使 workspace lifecycle events 能和 tool execute tracing/audit 对齐。`anyagent.server.sandbox.workspace_snapshots` 已承载 local-file / S3-compatible snapshot store（S3 走 `anyagent[s3]` optional extra）；`anyagent.server.sandbox.workspace_persistence` 已承载 local-file/Postgres workspace metadata store、in-memory/Redis workspace lease store 与 `hold_workspace_lease`（Postgres/Redis 依赖保持 lazy optional）；`anyagent.server.sandbox.opensandbox_backend` 已承载 OpenSandbox Lifecycle API + execd proxy workspace backend；`anyagent.server.sandbox.workspace_service` 已承载 restore/hibernate/delete/health/event 编排；`anyagent.server.sandbox.workspace_runtime` 已承载 metadata/lease/snapshot/event/backend/service runtime assembly builder；`ToolRuntimeSettings` 已纳入 sandbox/OpenSandbox/workspace metadata/lease/snapshot/event/SQL/Redis/S3 env 并组装为 `WorkspaceRuntimeConfig`；`create_tool_runtime_app(..., workspace_runtime=...)` 已能消费 `WorkspaceRuntimeAssembly`，`create_tool_runtime_app_async` 与 CLI `anyagent tool-runtime serve` 已能从 Core process config 构造该 assembly，让 `exec` 和 admin sandbox endpoint 共享 `WorkspaceService`，并覆盖 local-file metadata/snapshot 跨实例恢复；`anyagent.server.security.credential_runtime` 已承载 Tool Runtime credential resolver/admin-store assembly builder。`apps/tool-runtime` 已删除；manifest/execute/admin route 真源只在 Core。
- `anyagent.agent_runtime.multiagent` 已成为 multi-agent manager、thread store、system tool schema 与 stable root thread id 的共享真源；迁移期 apps Agent API 已直接消费 Core manager，不再保留兼容 re-export。
- `anyagent.server.security.mcp_credentials` 已成为 Agent API / Core `anyagent serve` MCP credential resolver 的共享真源，覆盖 `none` / `env` / `file` / `infisical`；迁移期 apps Agent API 已直接消费 Core resolver，不再保留兼容 re-export。
- `anyagent.server.security.credential_backends` 已承载 Tool Runtime 可复用的 `CredentialStore` interface、`EnvBackend`、`FileBackend` 与 read-only `InfisicalBackend`，Core standalone Tool Runtime 已提供 `/admin/credentials` set/list/delete；`anyagent.server.security.credential_runtime` 已承载 Tool Runtime credential resolver/admin-store assembly builder，统一 Core standalone 的 `MCP_CREDENTIAL_STORE_BACKEND` resolver/write 模式与 apps 历史 `CREDENTIAL_STORE_BACKEND` admin-store 模式；`anyagent.server.security.credential_capabilities` 与 `/admin/credentials/capabilities` 已提供 resolver/admin-store 能力矩阵。apps Tool Runtime 仅保留 Settings -> Core config 适配；db/vault backend 属于 Core optional backend 边界，不由 `anyagent-apps` 承担真源。
- `anyagent.storage.replay` 已开始承载 `/internal/events/*` 的 replay/list/stream 共享语义；`anyagent.server.internal_events.create_internal_events_router` 已提供可复用 router factory，迁移期 apps Agent API 直接挂载 Core router。
- `anyagent.server.internal_skills.create_internal_skills_router` 已承载 `/internal/skills/list` 的可复用 router factory，复用 Core agent catalog、skills loader/enablement、protocol response model 与 OpenAI-compatible auth/error helper；迁移期 apps Agent API 直接挂载 Core router，不再保留 apps 侧 internal skills router。
- `anyagent.storage.replay` 也已开始承载 external SSE replay 与 final-response wait 这类幂等回放 helper
- `anyagent.storage.external` 已开始承载 runtime 级 `Postgres/Redis` adapter，与 typed `ExternalSqlBackendConfig` / `MySQLDsn` contract
- built-in server 也已开始通过 `SQL_BACKEND_DIALECT` 选择 SQL backend；当前 MySQL 路径走 `anyagent.storage.external`，PostgreSQL 仍保持默认/稳定主路径
- `anyagent.storage.external.migrations` 已开始承载共享 schema apply helper；Core CLI 已提供 `storage-migrate` / `storage migrate`、`storage retention` / `storage-retention`、`storage replay` / `storage-replay`
- built-in `anyagent.server.persistence.storage_backends` 已与 `storage.external` 共享 SQL dialect 选择与 MySQL 路径；server 层保留的 glue 只负责 built-in 稳定默认路径、兼容 adapter 与 Redis 热层装配，SQL runtime 真源集中到 `storage.external`
- `anyagent.server.persistence.run_store` / `anyagent.server.persistence.session_store` / `anyagent.server.persistence.events` 中的 legacy PostgreSQL class 本体已不再作为独立实现存在，源码层只保留 wrapper / builder 级引用
- 真实 live matrix 已完成一轮最小闭环：built-in PG primary + Redis hot path、Redis lease live、built-in MySQL external path 与 apps MySQL storage smoke 均已通过
- `anyagent.storage.capabilities` 与 `/admin/storage/health.capabilities` 已开始作为 reference/external backend capability matrix 的事实来源
- `anyagent.agent_runtime.session_runtime` 已开始承载 built-in server 与 distributed `agent-api` 共用的 session prepare / snapshot persistence 编排
- `anyagent.server.handlers.http_errors` 已开始承载 `/v1/responses/{id}` 查询/取消路径共用的状态映射、最小 payload 组装、OpenAI-compatible 错误/鉴权与 cancel terminal event append；`anyagent.server.routes.responses_optional_router` 提供迁移期 apps Agent API 可直接挂载的 Core router。
- `anyagent.gateway.sequencer` 与 `anyagent.server.handlers.http_errors` 中的 OpenAI-compatible auth/error helpers 已成为迁移期 apps Agent API 的 keyed sequencing 与鉴权/错误响应真源；apps 侧旧 `auth.py`、`errors.py`、`keyed_sequencer.py` wrapper 已删除。
- `anyagent.protocol.openai_responses` 已开始承载 `response.completed` 事件的共享解析、canonical `response_id` 归一化与 fallback completion 组装
- `anyagent.server.responses.finalization` 已开始承载 run finalization / session snapshot persistence 的共享编排与终态状态映射

当前 apps 侧保留的内容：

- `apps/agent-api`、`apps/tool-runtime`、`apps/studio` 已删除，不保留兼容兜底。
- `scripts/dev/start_services.sh --mode tool-runtime|agent-api|stack` 使用已安装或 Yunxiao Packages PyPI 已发布的 `anyagent tool-runtime serve` / `anyagent agent-api serve` 启动服务。
- 业务 demo 需要新 SDK 能力时，先由 `anyagent` 仓 Yunxiao pipeline 发布 SDK 制品，再由 `anyagent-apps` 示例通过 `config/service-stack.toml` 消费最新 package。

## 4. Agent 安全边界

anyagent 的核心安全原则：**沙箱内自由，沙箱外隔离**。

沙箱采用**策略-后端分离**架构（参考 Codex）：策略定义在 `anyagent.protocol.sandbox`，后端实现可插拔（OpenSandbox / External / LocalUnsafe）。命令执行通过统一的 `exec` tool 路由到沙箱，对 agent loop 完全透明。

```text
┌────────────────── Agent Runtime ──────────────────────────┐
│                                                            │
│  Agent CAN DO (沙箱内自由, 通过 exec tool):                 │
│  ├─ 执行任意命令 (curl/wget/git/pip/python/node...)        │
│  ├─ 发起网络请求 (访问外部网站、调用外部 API)                │
│  ├─ 读写沙箱内文件 (创建/修改/删除)                         │
│  ├─ 安装依赖 (pip install / npm install / apt-get)         │
│  └─ 运行代码 (Python/JS/Shell 等)                          │
│  注: 同一 session 内多次 exec 共享沙箱 (会话隔离)           │
│                                                            │
│  Agent CAN SEE (只读可见):                                  │
│  ├─ 可用 Skills 列表 (name, description, schema)           │
│  ├─ 可用 MCP Servers 列表 (name, tools[])                  │
│  ├─ 可用 Tools 列表 (name, schema, kind)                   │
│  ├─ API Keys 别名 (credential_id, 不暴露实际值)             │
│  └─ Agent 自身的 AgentSpec (persona, constraints)          │
│                                                            │
│  Agent CAN USE (通过 server 中介):                           │
│  ├─ 调用 Tools → server 代为执行，自动注入 credential       │
│  ├─ 调用 MCP Tools → server 管理连接，agent 不持有连接       │
│  └─ 使用 API Keys → server 注入 header，agent 不见原值     │
│                                                            │
│  沙箱隔离边界 (CANNOT escape):                              │
│  ├─ 沙箱不挂载宿主机环境变量 / 凭证文件                     │
│  ├─ 沙箱 egress 策略拒绝访问内部服务 (anyagent/PG/Redis)    │
│  ├─ 沙箱间相互隔离 (不可跨沙箱访问, per-session 隔离)       │
│  └─ 沙箱有资源限制 (CPU/内存/磁盘/超时/TTL)                │
│                                                            │
│  Server 中介层负责:                                         │
│  ├─ Credential Vault：密钥只有 set 没有 get                │
│  ├─ Tool Policy：deny 优先于 allow                         │
│  ├─ Context 隔离：_credentials 不回传给 Agent              │
│  ├─ Sandbox 策略-后端分离：                                 │
│  │   ├─ Protocol 层: SandboxPolicy (策略声明)              │
│  │   ├─ Backend 层: OpenSandbox / External / LocalUnsafe   │
│  │   └─ SandboxManager: per-session 生命周期管理            │
│  └─ Audit：所有工具调用结构化留痕 (不含敏感值)              │
└────────────────────────────────────────────────────────────┘
```

详细设计见 `docs/security/sandbox-security.md`。

## 5. 部署模式对比

| 维度 | anyagent serve (内置) | anyagent-apps (分布式) |
|---|---|---|
| 启动 | `anyagent serve` | `docker-compose up` |
| 存储 | in-memory（可选 SQLite） | PostgreSQL + Redis |
| Tool Runtime | 进程内执行 | 独立服务（可多实例） |
| 并发 | 单进程 keyed serialization | 分布式 lease lock |
| 事件补发 | 内存 event buffer | Event Store + `last_seq` 补发 |
| 适用 | 开发/原型/小团队 | 企业级生产 |
| 沙箱后端 | OpenSandboxBackend / LocalUnsafe | ExternalSandboxBackend (Pod 即沙箱) |
| 凭证管理 | EnvBackend（环境变量） | FileBackend / DatabaseBackend / VaultBackend |

## 6. 依赖方向（单向）

```text
anyagent-apps ──depends-on──▶ anyagent

anyagent-apps 的 pyproject.toml:
  anyagent = { path = "../../../anyagent/packages/anyagent", editable = true }
```

禁止反向依赖：`anyagent` 不得 import `anyagent-apps` 的任何模块。
