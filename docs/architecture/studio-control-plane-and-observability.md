<!--
---
doc_kind: architecture
status: draft
tags: ["studio", "control-plane", "observability", "skills", "mcp"]
summary: AnyAgent Studio mode split, control-plane toggles, skill channels, and observability contract.
req: ["requirements.md#req-2-1", "requirements.md#req-2-2", "requirements.md#req-4", "requirements.md#req-5-2"]
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

连接配置由 Configure 页承载，开发环境默认从 `VITE_ANYAGENT_BASE_URL`、`VITE_ANYAGENT_API_KEY`、`VITE_ANYAGENT_ADMIN_KEY`、`VITE_ANYAGENT_MODEL` 和 `VITE_ANYAGENT_AGENT_ID` 注入。用户在浏览器里编辑 `base_url`、API key、admin key 时先进入草稿态，只有点击 Test 或 Apply 后才触发请求，避免输入中途反复刷新 catalog。Apply 后配置以版本化 localStorage 保存，之后 agent catalog、OpenAI-compatible chat、admin 文件/skills/MCP/credentials、observability/debug 查询都统一消费这份活动配置；Reset 会清除浏览器保存值并回到环境默认值。保存范围仅限当前浏览器，密钥不会写回 agent workspace 文件。

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

Studio Observability 页面现已消费 runs/summary/metrics/tools/errors/timeline/trace：顶部展示 agent/session 级聚合指标，History 可选择具体 response/run 做 drill-down，也可按 `trace_id` 拉取跨 response 时间线；Aggregation 区提供 source/status/tool 过滤、工具聚合、错误列表与 telemetry timeline。`/internal/events/list` 仍作为 Debug 页和单 run 回放的低层入口，不再是 Studio 聚合观测的唯一来源。

AnyAgent SDK 也提供 `client.observability` namespace，覆盖 runs、summary、timeline、metrics、tools、errors 与 trace 查询，用于业务 demo、验收脚本和外部控制台复用同一 typed API。

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
| Sessions | 查看当前 agent/session 的历史运行 | `/internal/observability/runs`、`/v1/responses/{id}`、`/internal/events/list` | run list、status/latency/stream、选择 run、查看消息与事件摘要、查看或取消 response（当 server 支持时） |
| Observability | 聚合分析 agent 运行质量 | `/internal/observability/metrics|tools|errors|timeline|trace|summary` | token/latency/tool/MCP/error 指标、timeline、tool 聚合、trace drill-down、迭代建议 |
| Evaluations | 把真实 run 转成评测种子 | observability runs/summary/timeline | candidate runs、按错误/高延迟/高价值筛选、inspect run、生成 evaluation seed 草稿；不假设独立 dataset/eval API 已存在 |
| Prompts | 面向使用者解释当前请求上下文 | `/internal/prompt/bundle`、`/internal/events/list` 中 `anyagent.prompt.context` | prompt preview 摘要、选中 skills、工具上下文、cache key；默认只展示解释视图，不鼓励直接改源文件 |
| Settings | 管理个人 Studio 连接与运行默认值 | localStorage、`/healthz` | server connection、API key、默认 agent/session/model、连接测试；不展示危险 admin 写操作 |

### 3.3 Build 模式页面

| 页面 | 用户目标 | 数据源 | 核心功能 |
|---|---|---|---|
| Home | 查看构建工作台摘要 | agent detail、files、skills、tools、MCP、credentials | 当前 agent 配置健康、未保存变更、能力启用概览、跳转各构建页 |
| Agents | 创建、复制、选择和管理 agent pack | `/internal/agents`、`/admin/workspace/agents` | catalog、创建 agent、exposed 状态、spawn-only agents、agent detail、跳转 Configure/Files |
| Configure | 编辑常用 `agent.yaml` 配置 | `/admin/workspace/agents/{id}/config`、agent detail、workspace files、skills/MCP/credentials admin API | connection draft/apply、create agent、source files、effective config、skills、credentials、MCP drafts；常用开关汇总，源码编辑保留为恢复路径 |
| Skills | 管理 agent-local skills | `/internal/skills/list`、`/admin/workspace/agents/{id}/skills/*` | import/install/update、channel 选择、enable/disable、default-selected、source metadata |
| MCP | 管理 MCP server drafts | `/admin/workspace/agents/{id}/files/mcp_json`、`mcp.json` parser/builder | streamable HTTP/SSE/stdio draft、enabled、credential ref、保存 mcp.json、invalid JSON recovery |
| Tools | 管理工具披露与 catalog | `/internal/tools/catalog`、`/admin/tools/catalog`、agent config | effective tools、available tools、requested tool names toggle、kind/reason/toolset version |
| Credentials | 管理 Credential Vault refs | `/admin/credentials`、`/admin/credentials/capabilities` | create/list/delete refs、scope、kind、只写 secret、能力矩阵 |
| Debug | 调试 run 的低层事件与协议 payload | `/internal/events/list|stream`、`/internal/prompt/bundle` | stage events、tool/command/result、raw event JSON、response id selector、prompt bundle raw view |
| Files | 编辑 agent pack 源文件 | `/admin/workspace/agents/{id}/files`、`PUT .../files/{kind}` | AGENTS.md/agent.yaml/mcp.json editor、sha256 optimistic save、reload、disabled editor state |
| Settings | 管理 Studio 与 server 管理面 | localStorage、health/admin endpoints | connection、admin key test、storage health、credential capability、server management diagnostics |

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
| `hooks/useMcpDrafts.ts` | 从 `mcp_json` 源文件解析 MCP draft、维护 invalid/recovery 状态，并通过 admin file API 写回 `mcp.json`。 |
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
- Evaluation handoff 当前基于 observability run/timeline 选择和 inspection，不定义独立 dataset/eval backend contract。

## 7. 验收要求

- 切换模式不丢失当前 agent、session key、连接配置。
- 修改 server `base_url` / API key / admin key 时先进入草稿态；Test 能用草稿配置验证 agent catalog/detail，Apply 后所有 chat、admin、debug、observability 调用都切到新连接，刷新页面仍保留应用后的配置。
- 折叠侧边栏后所有菜单仍能通过图标和 tooltip 访问。
- 任一 skill/MCP/tool 的胶囊开关保存后，源码文件可见等价变化。
- 任一源码文件手工修改后，表单重新加载能回填或明确进入 invalid/recovery 状态。
- Observability 页面能从 agent/session 聚合指标追到具体 response/run、tool、error、audit_ref、trace_id 与事件历史，并聚合出 token、latency、tool/MCP/skill 指标。
