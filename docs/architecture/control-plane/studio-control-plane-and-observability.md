<!--
---
doc_kind: architecture
status: draft
tags: ["studio", "control-plane", "observability", "skills", "mcp"]
summary: AnyAgent Studio mode split, control-plane toggles, skill channels, and observability contract.
req: ["requirements.md#req-2-1", "requirements.md#req-2-2", "requirements.md#req-4", "requirements.md#req-5-2", "requirements.md#req-5-13", "requirements.md#req-3-1", "requirements.md#req-14"]
---
-->

# Studio Control Plane and Observability

本文固定 AnyAgent Studio 的控制面与观测面口径。内置 Studio 源码随 `anyagent` Python package 打包；协议模型、agent 配置语义、skill/MCP/tool enablement、观测事件与 SDK 查询面属于 `anyagent`，业务示例和外部部署模板由 `anyagent-apps` 消费。

## 1. 模式分层

Studio 左上角 `AnyAgent` logo 区域应成为工作模式切换入口，提供两个模式：

| 模式 | 目标用户 | 主路径 | 侧边栏菜单 |
|---|---|---|---|
| Agent 使用模式 | 运营、销售、交付、非工程使用者 | 选择 agent、运行会话、查看历史与观测、反馈问题 | Home、Agents、Sessions、Observability、Evaluations、Prompts、Settings |
| Agent 研发模式 | agent builder、研发、解决方案工程师 | 创建/配置 agent、调试 prompt/tool/skill/MCP、导入能力、验证变更 | Home、Agents、Configure、Skills、MCP、Tools、Credentials、Debug、Files、Settings |

两种模式都共享当前 workspace、agent selector、连接状态、用户凭据状态。侧边栏折叠/展开是全局 UI 状态，不改变路由语义；折叠时保留图标与 tooltip。

连接配置由 Configure 页承载，开发环境默认从 `VITE_ANYAGENT_BASE_URL`、`VITE_ANYAGENT_API_KEY`、`VITE_ANYAGENT_ADMIN_KEY`、`VITE_ANYAGENT_MODEL` 和 `VITE_ANYAGENT_AGENT_ID` 注入；未设置 `VITE_ANYAGENT_MODEL` 时，Studio 不发送 `model` 字段，由 Agent Server 使用 agent/workspace 默认模型。用户在浏览器里编辑 `base_url`、API key、admin key 时先进入草稿态，只有点击 Test 或 Apply 后才触发请求，避免输入中途反复刷新 catalog。Apply 后配置以版本化 localStorage 保存，之后 agent catalog、OpenAI-compatible chat、admin 文件/skills/MCP/credentials、observability/debug 查询都统一消费这份活动配置；Reset 会清除浏览器保存值并回到环境默认值。保存范围仅限当前浏览器，密钥不会写回 agent workspace 文件。

## 2. 观测面归属

数据观测默认放在 Agent 使用模式下的 `Observability`，因为其首要问题是“当前 agent 被真实使用时发生了什么”。研发模式不复制完整页面，而是在 `Debug`、`Configure`、`Skills`、`MCP`、`Tools` 等页面提供跳转与局部摘要，用观测结果驱动 agent 迭代。

`Observability` 至少支持以下粒度：

- 指定 agent 的完整历史记录：按 session、response/run、turn、event 展开。
- 指定 agent 的工具调用观测：tool name、kind、status、latency、error、调用参数摘要、结果摘要、credential/policy 引用摘要。
- 指定 agent 的 MCP 调用观测：server label、transport、tool name、status、latency、error、credential ref。
- 指定 agent 的 skill 查看次数与选择情况：skill stable id、source hash、selected/default-selected、disclosed count、实际引用/触发线索。
- 指定 agent 的轮数统计：session turn count、run count、每轮输入/输出字符长度、平均/分位长度。
- LLM 调用事件统计：model、provider、input tokens、output tokens、cached input tokens、first-token latency、total response latency、finish reason、error。

当前实现已从 per-response v0 提升为 Core typed telemetry query 面：Studio 不直连日志库，也不承担存储适配；它只消费 Core 的 `/internal/observability/*` typed API。Core 侧新增 `TelemetryStore` 查询门面，底层由 Run Store、Event Store 与 normalized telemetry ingest store 聚合；启用 `STORAGE_MODE=external` 且配置 `POSTGRES_DSN` 时，normalized telemetry 会写入 PostgreSQL `telemetry_events` 表。其他日志/分析后端不属于 Studio 契约；持久化实现替换为 ClickHouse、Loki、ES 或 HTTP collector 时，也必须保持 Studio 调用契约不变。

写入侧统一 contract 是 `anyagent.protocol.observability.NormalizedTelemetryEvent`，`source` 使用 `TelemetrySource = run | event | stage | observability | workspace | audit`。`TelemetryStore` 必须提供 `ingest(event)` / `ingest_many(events)` 与 typed 查询方法；adapter 可以从 Run/Event/StageEvent/ObservabilityEvent/WorkspaceEvent/AuditEvent 转成同一个 normalized row，再进入查询层。当前 reference implementation 已将 Run Store、Event Store、structured log/audit sink 与显式 ingest 的 workspace/audit 事件一起合并进 timeline/tools/errors/traces 查询；PostgreSQL adapter 持久化同一个 normalized row，不要求 Studio 或 SDK 感知数据库差异。

已落地的查询入口：

- `/internal/observability/runs`：按 agent/session/response/time window/limit 查询 response-run 历史。
- `/internal/observability/summary`：查询单个 response 的 token、latency、tool/MCP/skill、turn/字符数摘要。
- `/internal/observability/timeline`：把 run、stage event、structured observability event 归一成时间线，支持 `trace_id` 过滤。
- `/internal/observability/metrics`：聚合 run_count、event_count、tool/MCP/error count、tokens、平均/最大 latency。
- `/internal/observability/tools`：按 tool name 聚合 planned/result/error、duration 与 audit refs。
- `/internal/observability/errors`：归一化 run error、stage error、structured log error。
- `/internal/observability/traces/{trace_id}`：按 trace 串起 response ids、audit refs 与时间线事件。
- `/internal/observability/alerts`：查询由 alert evaluator 写入的主动监控事件，v0 默认消费 `anyagent.agent.loop_warning` 与 `anyagent.agent.loop_terminated`。
- `/internal/audit/events`：按 credential_id / agent_id / session_key / response_id / trace_id / 时间窗查询独立审计事件。

Studio Observability 页面现已消费 runs/summary/metrics/tools/errors/timeline/trace：顶部展示 agent/session 级聚合指标，History 可选择具体 response/run 做 drill-down，也可按 `trace_id` 拉取跨 response 时间线；Aggregation 区提供 source/status/tool 过滤、工具聚合、错误列表与 telemetry timeline。`/internal/events/list` 仍作为 Debug 页和单 run 回放的低层入口，不再是 Studio 聚合观测的唯一来源。

AnyAgent SDK 也提供 `client.sessions`、`client.evaluations`、`client.observability` 与 `client.audit` namespace，分别覆盖 session 列表/详情、dataset CRUD/eval run、runs/summary/timeline/metrics/tools/errors/trace/alerts 查询，以及独立 audit event 查询，用于业务 demo、验收脚本和外部控制台复用同一 typed API。

Alert v0 的 wire model 定义在 `anyagent.protocol.alerts`：`AlertRule` / `AlertEvent` / `AlertChannel` / `AlertEventsResponse`。内置 server 启动时创建 in-memory rule store 与周期 evaluator，从 existing telemetry timeline 读取 loop warning/terminated stage event，去重后写入 alert event store；`AlertChannel(kind="webhook")` 是当前唯一 fan-out adapter。error rate / latency threshold 仍沿用同一 rule/evaluator 扩展点添加，不要求 Studio 直连指标库。

### 2.1 三类 Replay 持久化与查询面

聚合查询面之外，系统持久化三类“可重放级”payload，用于事后逐字回放某个 response 的真实输入与中间过程。它们与 §2 的 normalized telemetry 是两条独立通路：telemetry 服务“质量聚合”，replay 服务“逐字还原”。三类 replay 都以 stage event 形式落入 event store，再经独立查询端点取回，对应需求锚点 `requirements.md#req-5-13`。这套数据的边界、脱敏与 retention 决策见 `decisions/observability-replay-sink-and-retention.md`。

三类事件定义在 `packages/anyagent/src/anyagent/protocol/stage_events.py`，各自存什么：

| 类别 | 事件类 / type | 存什么 | 写入器 |
|---|---|---|---|
| Prompt context（rendered） | `AnyAgentPromptContextRenderedEvent` / `anyagent.prompt.context.rendered`（`stage_events.py:281`） | 注入后**完整渲染的 prompt 片段** `fragments: list[RenderedPromptFragment]` 加 `total_chars`、`prompt_cache_key`；区别于仅做摘要审计的 `anyagent.prompt.context`（`stage_events.py:275`） | `PromptContextPersistence.persist`（`persistence/prompt_context.py:53`） |
| Tool execution（detail） | `AnyAgentToolExecutionDetailEvent` / `anyagent.tool.execution.detail`（`stage_events.py:246`） | 单次工具调用的**完整 input/output 加 timing**：`arguments_json`、`output`、`status`、`duration_ms`、`output_truncated`、`error`、`audit_ref`；补足 planned/result 摘要无法回放的全量 payload | `ToolExecutionPersistence.persist`（`persistence/tool_execution.py:49`） |
| Model request | `AnyAgentModelRequestEvent` / `anyagent.model.request`（`stage_events.py:261`） | 发往模型 provider 的**首个请求体 `applied_body`**（即 prompt envelope 注入后的完整 body）加 `prompt_cache_key`；落库前脱敏 | `ModelRequestPersistence.persist`（`persistence/model_request.py:51`） |

写入开关与体积上限统一收口在 `PersistenceConfig`（`persistence/config.py:8`），默认全开、production-safe：`persist_rendered_context` 加 `rendered_context_max_bytes`（默认 512KiB，超限截断 rendered fragments）、`persist_tool_execution_detail` 加 `tool_execution_max_bytes`（256KiB，超限置事件 `output_truncated`）、`persist_model_request` 加 `model_request_max_bytes`（1MiB）。rendered prompt context 由“总序列化字节数”而非条数治理。

三个查询端点收口在 `packages/anyagent/src/anyagent/server/internal_replay.py`，均从 event store 按 `response_id` 扫描分页、取目标 type 的最新一条，返回 `anyagent.protocol.agent_api_internal` 下的稳定 SDK 模型（公共兼容边界）：

- `GET /internal/responses/{response_id}/tool-executions`（`internal_replay.py:31`）→ `InternalResponseToolExecutionsResponse`，回放全部 tool execution detail。
- `GET /internal/responses/{response_id}/model-request`（`internal_replay.py:60`）→ `InternalResponseModelRequestResponse`，回放 `applied_body` 加 `prompt_cache_key`。
- `GET /internal/responses/{response_id}/prompt-context`（`internal_replay.py:90`）→ `InternalResponsePromptContextResponse`；优先返回 rendered fragments（`fallback="rendered"`），缺失时降级为审计摘要（`fallback="audit"`）。

### 2.2 Observability Sink Envelope、脱敏与 Replay Retention

**统一出口 envelope。** 上述 replay payload 除了供 SDK/HTTP 查询，还经一条 server 内部 sink 通路对接外部审计/OTel。出口模型是 `ReplayObservabilityEnvelope`（`packages/anyagent/src/anyagent/observability.py:27`，`extra="forbid"`，含 `schema_version`、`category`、`event_type`、`response_id`、`seq`、`trace_id`、`ts_ms`、`payload`）。关键边界：**envelope 是 server 内部模型，不进 protocol bundle、不生成 TypeScript 类型**——把出口格式当对外 wire contract 会迫使大体积、需随后端演进的数据背上 schema 兼容承诺。`build_replay_observability_envelope`（`observability.py:213`）只接受 `REPLAY_EVENT_TYPES`（`observability.py:18`，即上述三个 type）的 stage event，按 `_replay_category` 映射 category 后封装。Sink 接口 `ReplayObservabilitySink`（`observability.py:81`）是 additive 的：内置从 `StdoutJsonReplaySink`（`observability.py:91`）与 `FileJsonlReplaySink`（`observability.py:98`，按行追加 JSONL）起步，OTel 作为同一 envelope 背后的 adapter 接入，而非核心循环的直接依赖；经 `ANYAGENT_REPLAY_OBSERVABILITY_STDOUT` / `ANYAGENT_REPLAY_OBSERVABILITY_FILE` 配置（`observability.py:269`）。这与面向 `ObservabilityEvent` 的 `LoggingSink`/`HttpJsonSink`（`observability.py:50`、`observability.py:62`）是两套并行 fan-out。

**脱敏策略。** model request 落库前剥离凭证：`ModelRequestPersistence.persist` 在构造事件时对 `applied_body` 调 `redact_replay_payload`（`persistence/model_request.py:68`），同时 envelope 封装时 `payload` 也再过一次 `redact_replay_payload`（`observability.py:236`）。脱敏键集合见 `_is_sensitive_key`（`observability.py:346`），命中 `authorization`、`credential_id`、`api_key`、`token`、`secret`、`auth_ref` 等（连字符/下划线归一）即递归替换为 `[REDACTED]`。因此 Authorization 头、credential_id 等注入材料不会以明文进入持久化 replay 或外部 sink，对应需求锚点 `requirements.md#req-3-1`。

**独立 retention。** replay 事件体积远大于普通审计/run 事件，故走**独立 TTL 且过期更早**：`replay_event_store_retention_s` 默认 1 小时（`storage/settings.py:33`），短于通用 `event_store_retention_s` 的 2 小时（`storage/settings.py:32`）与 `session_store_retention_s` 的 24 小时。清理由 `prune_expired_replay_events`（`server/persistence/events.py:799`）按 `REPLAY_EVENT_TYPES` 定向裁剪触发，event store 各后端实现 `prune_replay_events`：内存后端 `storage/inmemory.py:381`、SQLAlchemy 外部后端 `storage/external/sqlalchemy_backend.py:404`、合约定义 `storage/contracts.py:95`。replay TTL 与 run/session retention 各自配置，互不绑定。

## 3. 页面功能设计稿

Studio 的页面设计必须从 AnyAgent Server 的真实控制面出发，而不是把同一组组件套多个标题。页面分成共享壳、Use 模式页面和 Build 模式页面三层。Use 与 Build 可以复用底层 typed client 和数据 cache，但页面任务、默认动作、风险级别和文案必须明显不同。

### 3.1 全局壳

所有页面共享以下上下文：

- 当前 AnyAgent Server 连接：`base_url`、API key、admin key、连接测试状态、catalog 状态，默认来自 `VITE_ANYAGENT_*`，Apply 后保存到浏览器 localStorage。
- 当前 agent：来自 `/internal/agents` 或 `/admin/workspace/agents/{agent_id}`，切换后影响 chat、sessions、observability、configure、skills、MCP、tools、files。
- 当前 session：写入 `/v1/responses` metadata `session_key`，用于 sessions/observability 查询过滤。
- 当前 run/response：chat 运行后得到 `response_id`，用于 `/internal/events/list`、`/internal/observability/summary` 与 trace drill-down。
- 全局导航只保留左侧 sidebar；内容区不得再出现重复的全局 Tabs。页面内可以有局部筛选器、分段控件或表格视图，但不能伪装成第二套主导航。

### 3.2 Use 模式页面

| 页面 | 用户目标 | 数据源 | 核心功能 |
|---|---|---|---|
| Home | 运行当前 agent，快速确认服务与最近运行状态 | `/v1/responses`、`/internal/events/list`、`/internal/agents/{id}` | client session、live stream、最近 run 摘要、agent 能力概览、跳转 Sessions/Observability |
| Agents | 选择可用 agent 并理解它能做什么 | `/internal/agents?include_unexposed=true`、`/internal/agents/{id}` | agent picker、active agent 摘要、模型/技能/工具能力说明、开始会话入口；不暴露创建/写文件等构建操作 |
| Sessions | 查看当前 agent/session 的历史运行 | `/internal/sessions`、`/internal/sessions/{key}`、`/internal/observability/runs`、`/v1/responses/{id}`、`/internal/events/list` | session list、会话级聚合、run list、status/latency/stream、选择 run、查看消息与事件摘要、查看或取消 response（当 server 支持时） |
| Observability | 聚合分析 agent 运行质量 | `/internal/observability/metrics|tools|errors|timeline|trace|alerts|summary` | token/latency/tool/MCP/error 指标、timeline、tool 聚合、trace drill-down、主动告警、迭代建议 |
| Evaluations | 把真实 run 转成可复跑评测资产 | `/internal/evaluations/datasets`、`/internal/evaluations/run`、`/internal/evaluations/runs`、observability runs/summary/timeline | dataset CRUD、candidate runs、按错误/高延迟/高价值筛选、inspect run、生成 evaluation seed、执行 exact-match v0 评测、查询历史结果 |
| Prompts | 面向使用者解释当前请求上下文并跟踪跨版本演进 | `/internal/prompt/bundle`、`/internal/prompt/versions`、`/internal/prompt/versions/diff`、`POST .../versions/{id}/restore`、`/internal/events/list` 中 `anyagent.prompt.context` | prompt preview 摘要、选中 skills、工具上下文、cache key、版本快照、版本 diff、admin-gated restore；默认解释当前上下文，版本操作进入显式动作 |
| Settings | 管理个人 Studio 连接与运行默认值 | localStorage、`/healthz` | server connection、API key、默认 agent/session/model、连接测试；不展示危险 admin 写操作 |

### 3.3 Build 模式页面

| 页面 | 用户目标 | 数据源 | 核心功能 |
|---|---|---|---|
| Home | 查看构建工作台摘要 | agent detail、files、skills、tools、MCP、credentials | 当前 agent 配置健康、未保存变更、能力启用概览、跳转各构建页 |
| Agents | 创建、复制、选择和管理 agent pack | `/internal/agents`、`/admin/workspace/agents` | catalog、创建 agent、exposed 状态、spawn-only agents、agent detail、跳转 Configure/Files |
| Configure | 编辑常用 `agent.yaml` 配置 | `/admin/workspace/agents/{id}/config`、agent detail、workspace files、skills/MCP/credentials admin API | connection draft/apply、create agent、source files、effective config、skills、credentials、MCP drafts；常用开关汇总，源码编辑保留为恢复路径 |
| Skills | 管理 agent-local skills | `/internal/skills/list`、`/admin/workspace/agents/{id}/skills/*` | import/install/update、channel 选择、enable/disable、default-selected、source metadata |
| MCP | 管理 MCP server drafts 与运行态 | `/admin/workspace/agents/{id}/mcp/servers`、`PUT .../mcp/servers/{label}/enabled`、`POST .../mcp/servers/{label}/test`、`/admin/workspace/agents/{id}/files/mcp_json` | streamable HTTP/SSE/stdio draft、enabled/disabled/inherited 摘要、credential ref、连接测试、保存 mcp.json、invalid JSON recovery |
| Tools | 管理工具披露与 catalog | `/internal/tools/catalog`、`/admin/tools/catalog`、agent config | effective tools、available tools、requested tool names toggle、kind/reason/toolset version |
| Credentials | 管理 Credential Vault refs | `/admin/credentials`、`/admin/credentials/capabilities` | create/list/delete refs、scope、kind、只写 secret、能力矩阵 |
| Debug | 调试 run 的低层事件与协议 payload | `/internal/events/list|stream`、`/internal/prompt/bundle`、`/admin/sandboxes`、`/admin/sandboxes/workspaces/{id}/snapshots`、`POST .../reclaim` | stage events、tool/command/result、raw event JSON、response id selector、prompt bundle raw view、sandbox workspace 列表、snapshot drill-down、强制回收 |
| Files | 编辑 agent pack 源文件 | `/admin/workspace/agents/{id}/files`、`PUT .../files/{kind}` | AGENTS.md/agent.yaml/mcp.json editor、sha256 optimistic save、reload、disabled editor state |
| Settings | 管理 Studio 与 server 管理面 | localStorage、health/admin endpoints | connection、admin key test、storage health、credential capability、sandbox/workspace diagnostics、server management diagnostics |

### 3.4 页面拆分验收

- 每个 sidebar item 必须有唯一页面 key，active 状态只由该 key 决定。
- 每个页面必须有自己的主任务、标题、副标题、关键数据和至少一个页面独有区块；允许复用组件，但不能只换标题。
- Use 与 Build 的同名页面可以共享底层数据，但主任务不同。例如 Use/Agents 偏选择与运行入口，Build/Agents 偏创建与配置入口；Use/Settings 偏个人连接，Build/Settings 偏 admin/health/capability。
- 顶部 project quick actions 只能跳到页面 key，不能触发隐藏的 tab group。
- 当某页后端 API 尚未存在时，页面应显示真实待办状态和可追溯数据来源，而不是假数据。

### 3.5 前端模块组织

Studio 前端代码按 protocol-first 和页面职责拆分，避免继续把所有状态、路由、工具函数和页面 JSX 堆进单文件：

| 模块 | 职责 |
|---|---|
| `anyagentClient.ts` | Studio 消费 AnyAgent Server 的 typed client facade。新增 server/admin/internal API 时先确认协议或 server endpoint，再在这里收口请求/响应类型。 |
| `navigation.tsx` | `StudioMode`、`StudioTab`、sidebar 分组、页面标题/副标题、页面 section 映射。Use/Build 同名页面差异从这里开始可见。 |
| `studioSettings.ts` | `VITE_ANYAGENT_*` 默认值、连接配置规范化、版本化 localStorage 读写。 |
| `studioUtils.ts` | JSON、hash、CSV、事件摘要、观测格式化、文件查找等无 UI 工具。 |
| `sampleData.ts` | 本地 UI 草稿样例，例如 MCP draft、SKILL.md seed。 |
| `hooks/useWorkspaceCatalog.ts` | workspace agent/skill catalog 加载与状态。 |
| `hooks/useAgentFiles.ts` | agent pack 源文件加载、编辑器状态、sha256 optimistic save 和文件启用态。 |
| `hooks/useMcpDrafts.ts` | 从 MCP admin API 与 `mcp_json` 源文件解析 MCP draft、维护 invalid/recovery 状态，并通过 server toggle/test 或 admin file API 写回 `mcp.json`。 |
| `hooks/useToolCatalog.ts` | effective tool catalog 与 registered tool pool 的 typed API 加载、状态和刷新。 |
| `hooks/useCredentials.ts` | Credential Vault refs 的列表、表单状态、只写 secret 保存和删除。 |
| `hooks/useSkillsManagement.ts` | agent-local skills 的 channel install/import、default-selected、disablement、update check/apply 与 source file refresh。 |
| `hooks/useObservability.ts` | Use 模式观测面的 runs/summary/metrics/tools/errors/timeline/trace 查询、筛选、run 选择与迭代建议。 |
| `pages/*Page.tsx` | 页面级组件。页面必须体现 Use/Build 的主任务差异，不能只换标题。当前已从主文件拆出 `HomePage`、`AgentsPage`、`SessionsPage`、`ObservabilityPage`、`EvaluationsPage`、`PromptsPage`、`SettingsPage`、`CredentialsPage`、`DebugPage`、`SkillsPage`、`McpPage`、`ToolsPage`、`FilesPage` 和 `ConfigurePage`；`StudioApp` 通过 `React.lazy` 按页面动态加载，`ConfigurePage` 作为 Build 组合页复用构建模块。 |
| `pages/configure/*Panel.tsx` | Configure 页的职责子面板。`ConnectionPanel` 管理浏览器连接草稿，`CreateAgentPanel` 只负责创建入口，`EffectiveConfigPanel` 只负责 `agent.yaml` 常用配置与协议摘要，`ToolCatalogSection` 复用 effective/available tool catalog 呈现。 |

`StudioApp.tsx` 只负责全局状态编排、跨页面动作、应用壳和暂未拆出的页面；每新增一页或让页面逻辑明显增长时，应优先进入 `pages/` 或 `hooks/`，而不是继续扩大 `StudioApp.tsx`。

## 4. Enable / Disable 配置语义

以下资源都需要支持 enable/disable：

- skills
- MCP servers
- registered/provided tools
- agent-pack source files or config sections

配置真源仍是 agent pack 内文件：`agent.yaml`、`AGENTS.md`、`mcp.json` 和 local `skills/**/SKILL.md`。后台页面可以通过胶囊按钮修改常用开关，同时必须保留源码编辑器作为兜底路径。

建议的配置落点：

| 资源 | 建议字段 | 备注 |
|---|---|---|
| skill | `skills.disabled` 或每个 skill ref 的 `enabled` 派生状态 | default-selected 与 enabled 分开；disabled 的 skill 不参与披露，也不能被设为 default-selected |
| MCP server | `mcpServers.<label>.enabled` | disabled server 不连接、不披露工具、不进入 prompt ref、不读取 credential |
| tool | `tools.disabled_tool_names` 或 policy deny entry | 与 `requested_tool_names` 分开，避免 “requested 但被禁用” 不可解释 |
| file/config section | admin file metadata、Studio editor enablement 或 `agent.yaml` section-level enabled | v0 已在 Studio 源码编辑面提供 Active/Disabled 胶囊控制编辑器状态；配置 section 通过现有 config/MCP 表单控制，不把浏览器直接删除文件作为禁用语义 |

服务端必须在 catalog/detail 响应中返回最终 enablement 摘要与原因，让 Studio 能解释胶囊按钮状态：enabled、disabled、inherited、policy-denied、missing、invalid。

## 5. Skill 导入渠道

`npx skills add` 不能作为唯一抽象。Core admin installer 应升级为渠道化导入：

- `skills.sh`：默认官方/半官方渠道，提交 package/channel/skill/ref，由服务端受限执行并复制到 agent-local skills。
- `github`：按 repo/ref/path 导入，并按来源 ref 检查更新/拉取更新。
- `local_upload`：粘贴或上传 `SKILL.md` 及必要 assets，保持当前本地导入路径。
- `registry`：保留现有 package + skill 的 installer 兼容层，但作为 channel adapter，而不是写死在 UI/协议里。

当前 Core admin installer 已接受 `channel` 字段，`skills.sh` 为默认渠道，`registry` 作为兼容渠道，`github` 支持受限的 `git clone --depth 1 --branch <ref>` 后从 repo 内指定 skill path 复制。导入/安装后的 agent-local skill 会写入 `.anyagent-skill-source.json`，记录 `channel`、`source_ref`、`installed_at`、`source_hash` 等来源元数据。Core admin API 已提供按目录的 update check/apply 入口，更新时按 channel adapter 执行并继续通过 loader 校验 frontmatter、路径边界、文件大小与重复冲突；`local_upload` 因缺少远端来源只返回不可更新原因。

## 6. 已实现边界

- PostgreSQL `telemetry_events` 是当前 external storage mode 下的 normalized telemetry 持久化 adapter。
- Studio 基于 latency、token、tool/MCP 调用数、skill 披露数和 turn 长度生成迭代建议，并跳转到对应页面。
- Sidebar page key 唯一；Use 模式 Home/Agents/Sessions/Observability/Evaluations/Prompts/Settings 与 Build 模式 Credentials/Debug/Skills/MCP/Tools/Files/Configure/Settings 均对应独立页面模块。
- Configure 的 connection、create-agent、effective-config 和 tool catalog 已下沉为组合组件；agent files、MCP drafts、tool catalog、credentials、skills management 与 Use 模式 observability 已收敛到专用 hooks。
- Studio 前端已做页面级 code splitting；主 bundle 不再携带所有 Use/Build 页面实现，页面模块按需加载。
- Sandbox / Workspace 运维 API 已提供 `GET /admin/sandboxes`、`GET /admin/sandboxes/workspaces/{id}/snapshots` 与 `POST /admin/sandboxes/workspaces/{id}/reclaim`，控制面可从 workspace ref 追到 generation、snapshot digest/bytes 与强制回收结果。
- Alert 后端已提供 `AlertRule` / `AlertEvent` / `AlertChannel` protocol、in-memory rule/event store、后台 evaluator、`GET /internal/observability/alerts` 查询面与 webhook fan-out；默认规则覆盖 loop warning / loop terminated。
- Evaluations 后端已提供 `EvalDataset` / `EvalCase` / `EvalRun` protocol、workspace-local `.anyagent/evaluations.json` reference store、dataset CRUD、`POST /internal/evaluations/run` 执行器与 run result 查询；执行器通过 server 内部 ASGI 调用复用 `/v1/responses` 主路径。
- Prompt 版本后端已提供 `PromptVersionSnapshot` / `PromptVersionSource` protocol、workspace-local `.anyagent/prompt_versions.json` reference store、`GET/POST /internal/prompt/versions`、`GET /internal/prompt/versions/{id}`、`GET /internal/prompt/versions/diff` 与 admin-gated `POST /internal/prompt/versions/{id}/restore`；它记录 workspace/agent prompt source 文件快照，与单次 rendered prompt replay 互补。

## 7. TypeScript SDK 集成策略

Studio 前端当前通过 `anyagentClient.ts` 以原始 fetch 重新实现了所有 API 调用。下一阶段应迁移到消费 `@anyagent/sdk` TypeScript SDK，获得 schema 校验、类型安全和协议演进保护。

### 7.1 迁移路径

| 阶段 | 范围 | 收益 |
|---|---|---|
| Phase 0 (当前) | `anyagentClient.ts` 原始 fetch | 零依赖、快速迭代 |
| Phase 1 | 将 SDK `client.ts` 作为 Studio 的 typed facade，替换 `anyagentClient.ts` 中的请求/响应类型 | 类型安全、schema 校验、协议版本锁定 |
| Phase 2 | 消费 SDK 的 `client.responses.stream()` SSE 方法替代 OpenAI SDK 直连 | 统一流式协议、支持 cancel/retrieve |
| Phase 3 | 消费 SDK 的 `client.sessions` / `client.observability` namespace 替代手动 fetch | 减少重复代码、自动 retry/cache |

### 7.2 当前未消费的 SDK 能力

Studio 应补充消费以下 SDK 端点：

- `client.responses.retrieve(responseId)` — 用于 Sessions 页展示 response 状态
- `client.responses.cancel(responseId)` — 用于 Home 页 chat 运行中取消
- `client.sessions.list()` / `client.sessions.get(sessionKey)` — 用于 Sessions 页展示会话聚合与 drill-down
- `client.events.stream(responseId)` — 用于 Debug 页实时 SSE 事件流
- `client.admin.plugins.catalog()` — 用于 Build/Tools 页展示 plugin 来源
- `GET /admin/credentials/capabilities` — 用于 Credentials 页展示 vault 能力矩阵（当前 Studio 已调用但 TS SDK 未暴露，需补充 SDK 方法）

### 7.3 SDK 与 Studio 类型对齐

Studio 的 `anyagentClient.ts` 导出的类型（`AgentDetail`、`ToolCatalog`、`ObservabilityRunItem` 等）应逐步替换为 SDK `protocol-types.ts` 中的 generated types。过渡期两套类型可共存，通过 type alias re-export 保持页面组件不感知迁移。

## 8. 高密度 UI 规范

Studio 采用高密度仪表盘风格（对标 Grafana/Datadog），信息密度优先于视觉留白。

### 8.1 密度原则

- **指标用内联 stat-strip 而非独立卡片**：一行展示 4-6 个 key-value 对，label 与 value 水平排列，不使用独立 Card 组件包裹每个指标。
- **减少嵌套层级**：页面 → section → 内容，不再有 section → Card → Card.Header → Card.Content → 内容。
- **紧凑间距**：全局 gap 从 12-16px 降至 6-10px，panel padding 从 16-18px 降至 10-12px，page-shell padding 从 24px 降至 16px。
- **表格优先于列表**：run history、tool stats、error list 使用紧凑表格行（32-36px row height），不使用带 padding 的卡片式列表项。
- **折叠默认**：timeline、error detail、turn breakdown 默认折叠，点击展开；首屏只展示聚合数字。
- **Monospace 数字**：所有数值使用 `font-variant-numeric: tabular-nums` 保证列对齐。

### 8.2 组件密度规格

| 组件 | 旧规格 | 新规格 |
|---|---|---|
| metric-card | 独立 Card, min-height 110px, padding 16px | stat-strip inline item, height 28px, padding 0 |
| panel | min-height 480px, border-radius 12px, padding 14-18px | min-height auto, border-radius 6px, padding 8-12px |
| panel-header | min-height 52px, padding 14px 18px | min-height 36px, padding 8px 12px |
| section-block | margin-bottom 20px, gap 12px | margin-bottom 12px, gap 6px |
| trace-row | min-height 48px, gap 18px, padding 0 16px | min-height 32px, gap 10px, padding 0 10px |
| timeline-event | padding 12px, gap 8px | padding 6px 8px, gap 4px |
| history-row | padding 12px 14px | padding 6px 10px |
| overview-card | min-height 200px, padding 24px | 移除，改为 stat-strip |
| empty-state | padding 24px | padding 12px |

### 8.3 Stat-strip 组件

替代 metric-grid + metric-card 的新组件：

```
.stat-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 16px;
  padding: 8px 12px;
  background: var(--frost);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 12px;
}
.stat-strip .stat {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
}
.stat-strip .stat-label { color: var(--ink-tertiary); }
.stat-strip .stat-value { font-weight: 600; font-family: var(--font-mono); color: var(--ink); }
```

### 8.4 页面密度验收

- Observability 页首屏（无滚动）应能同时展示：聚合指标条、run 列表前 8 行、tool 聚合前 5 行。
- Home 页 Use 模式首屏应能同时展示：连接状态、trace 表前 4 行、chat 输入区。
- Build/Home 首屏应能同时展示：所有配置健康指标 + 配置清单 + 构建信号。
- 任何页面的空状态占位不超过 80px 高度。

## 9. 实时数据与缓存模式

### 9.1 SSE 实时流

Studio 应消费 Core 的 SSE 端点实现实时更新：

| 场景 | 端点 | 消费方 |
|---|---|---|
| Chat 运行中事件 | `GET /internal/events/stream?response_id=` | Home 页 Live stream 面板 |
| Debug 实时回放 | `GET /internal/events/stream?response_id=` | Debug 页 stage event 面板 |
| Observability 增量 | 轮询 `/internal/observability/runs` + `/internal/observability/timeline` | Observability 页 auto-refresh |

SSE 连接管理：
- 使用 `EventSource` 或 `fetch` + `ReadableStream` 消费 SSE
- 连接在页面切换时自动断开（通过 `useEffect` cleanup）
- 断线后指数退避重连（1s → 2s → 4s → 8s → 停止）
- 每个 SSE 连接携带 `last_seq` 参数避免重复事件

### 9.2 数据缓存策略

引入轻量 SWR 模式（不引入外部库，基于 hooks 实现）：

```typescript
type CacheEntry<T> = { data: T; fetchedAt: number; stale: boolean };
```

- **staleTime**: 数据在 N 秒内视为新鲜，不重新请求
  - agent catalog: 30s
  - tool catalog: 15s
  - observability metrics: 10s
  - credentials: 60s
- **background refetch**: 数据过期后先返回缓存，后台刷新后更新 UI
- **deduplication**: 同一 key 的并发请求合并为一个

### 9.3 Debounce 与节流

- tool catalog 的 `requestedToolsText` 变更：300ms debounce
- observability filter 变更（source/status/tool）：200ms debounce
- skill search filter：150ms debounce
- connection draft 输入：不 debounce（草稿态不触发请求）

### 9.4 错误恢复

- 所有 API 调用失败后自动重试 1 次（间隔 1s）
- 连续 3 次失败后进入 degraded 状态，展示 inline error banner 而非清空数据
- 网络恢复后自动刷新当前页面数据

## 10. 验收要求

- 切换模式不丢失当前 agent、session key、连接配置。
- 修改 server `base_url` / API key / admin key 时先进入草稿态；Test 能用草稿配置验证 agent catalog/detail，Apply 后所有 chat、admin、debug、observability 调用都切到新连接，刷新页面仍保留应用后的配置。
- 折叠侧边栏后所有菜单仍能通过图标和 tooltip 访问。
- 任一 skill/MCP/tool 的胶囊开关保存后，源码文件可见等价变化。
- 任一源码文件手工修改后，表单重新加载能回填或明确进入 invalid/recovery 状态。
- Observability 页面能从 agent/session 聚合指标追到具体 response/run、tool、error、audit_ref、trace_id 与事件历史，并聚合出 token、latency、tool/MCP/skill 指标。
