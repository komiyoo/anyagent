## <!--

doc_kind: architecture
status: stable
tags: ["roadmap", "architecture", "anyagent"]
summary: anyagent 仓库的长期架构方向、当前事实锚点、设计边界与分阶段路线。

---

-->

# anyagent Architecture Direction & Roadmap

本文只记录 **anyagent 本仓** 的长期架构方向、当前事实锚点、关键边界与分阶段路线。

边界约定：

- 本文不规划 `anyagent-apps`、`amap-mcp-server` 或其他消费侧仓库的任何工作。各仓库 roadmap 各自维护。
- 具体任务状态、执行清单、验收记录维护在 `todo/*.md`、测试脚本或 release 记录中,本文只列出 Phase 级目标与对应 todo 入口。

---

## 1. 总体方向

anyagent 的目标是成为 **配置化、服务化的 AI Agent 基础设施**:

- `anyagent serve` 从 agent workspace 启动 OpenAI Responses API compatible server。
- Agent 通过 `AGENTS.md`、`agent.yaml`、`mcp.json` 和 local skills 配置运行;agent loop 只能看到被披露的资源、policy 和 credential ref。
- Python built-in server 是当前 reference implementation;protocol/schema bundle 是 runtime、SDK、Studio 和测试之间的兼容锚点。
- 多语言 SDK 从同一份 protocol/schema 派生 wire model,再叠加语言惯用 resource namespace 和 helper。
- runtime 可替换性以 contract tests 和 conformance fixtures 为准,不以代码结构相似性为准。

---

## 2. 当前事实锚点

| 领域           | 当前真源                                                                     | 已实现事实                                                                                             |
| -------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 协议           | `packages/anyagent/src/anyagent/protocol/`、`schema_export.py`               | 导出 JSON Schema bundle、endpoint manifest、semantic rules 与 OpenAPI 3.1 document。                   |
| Server         | `packages/anyagent/src/anyagent/server/app.py`                               | 提供 `/v1/responses`、`/internal/*`、`/admin/*` typed endpoints。                                      |
| CLI            | `packages/anyagent/src/anyagent/cli.py`                                      | 提供 `serve`、`init`、`doctor`、config、storage、workspace 等 control-plane 入口。                     |
| Python SDK     | `packages/anyagent/src/anyagent/agent_api_client.py`、`anyagent.types`       | OpenAI 兼容 client + events、agents、skills、tools、prompts、observability、admin、health namespaces。 |
| Model Provider | `packages/anyagent/src/anyagent/agent_runtime/model_providers/`、`docs/architecture/api/model-provider-translators.md` | OpenAI Responses provider 直透；Anthropic/Gemini 经统一 translator 宿主、capability 裁决与 registry 路由。 |
| TypeScript SDK | `sdks/typescript/`                                                           | 从 protocol export 生成 schema/types,通过 endpoint manifest 解析 schema-backed paths。                 |
| Stage Events   | `anyagent.protocol.events`                                                   | 覆盖 prompt context、model stream、tool planned/result、command planned/result 与 done 主路径。        |
| Storage        | `anyagent.storage`、server storage adapters                                  | 支持 in-memory、SQLite、PostgreSQL、Redis hot path 与 typed external SQL backend config。              |
| Tool Runtime   | `anyagent.tool_runtime`、server tool endpoints                               | manifest/execute contract、credential resolver/admin-store assembly、standalone Tool Runtime 管理面。  |
| Credential     | `anyagent.server.security.credential_*`                                      | Env/File/Infisical read-only backend、admin credential CRUD、capability matrix。                       |
| Sandbox        | `anyagent.protocol.sandbox`、sandbox backend modules                         | `SandboxPolicy`、`NetworkSandboxPolicy`、`ResourceLimits` 与 backend adapter 分层。                    |
| Studio         | `packages/anyagent/studio/`、`packages/anyagent/src/anyagent/studio_static/` | 源码位于 package workspace,构建产物随 Python package 打包,消费 typed API。                             |

---

## 3. 设计边界

### 3.1 Protocol / Spec

- `anyagent.protocol.*` 是 Python 侧 wire contract 真源。
- schema bundle 是非 Python runtime、非 Python SDK 和 Studio 的可消费协议出口。
- 无法直接表达为 JSON Schema 的 Pydantic 语义进入 semantic rules。
- endpoint manifest 记录 endpoint id、method、path、request/response schema 与 streaming 语义。
- compatibility matrix 记录 server、protocol、SDK、Studio 的已实现兼容关系。

### 3.2 Server Runtime

- Python built-in server 同时承担 reference server、开发 server 和协议验收基线。
- handler 在边界处消费 protocol model;runtime service 不依赖未校验的外部 shape。
- storage、credential、sandbox、tool runtime 通过 interface/adapter 分层,避免把 production backend 语义写死到 agent loop。
- 新 runtime 必须通过 Responses API、Stage Events、internal/admin API、Tool Runtime、storage/replay 的 contract tests 后才能替代生产主路径。

### 3.3 SDK

- 本仓负责 SDK 框架自身:protocol-derived wire DTO、序列化、runtime validation、namespace facade、conformance fixtures。
- SDK **不** 承担业务示例、部署模板、消费侧验收;这些归各自消费仓库。
- Python SDK 与 Python distribution 同包协作,public model facade 通过 `anyagent.types` 暴露。
- 非 Python SDK 位于 `sdks/<language>/`,生成层负责 wire DTO/serialization/validation,手写层只承载语言惯用 helper。
- SDK 不复制协议字段,不直接依赖 server runtime、agent runtime 或 workspace loader。
- 每个 SDK 的 public surface 必须能追到 protocol schema、generated model 或 Python protocol model。
- 新增 SDK 语言 scaffold 前提:有 conformance fixtures 覆盖目标主路径;没有真实集成需求不创建空壳包。

### 3.4 Studio

- Studio 是 typed API consumer,不读取 server 内部 Python 模块。
- Studio 只能消费 OpenAI Responses API、`/internal/*` 与 `/admin/*` typed API。
- Studio 连接、agent catalog、workspace files、skills、MCP、tools、credentials、observability 和 debug 均通过 shared typed client facade 收口。
- Studio 页面职责、观测面与 skill/MCP/tool enablement 见 [studio-control-plane-and-observability.md](../control-plane/studio-control-plane-and-observability.md)。

### 3.5 仓库边界

- `anyagent` = protocol、server、SDK、runtime primitives、Tool Runtime、credential/connector contract 与文档真源。
- 消费侧仓库(例如 `anyagent-apps`)如何使用 anyagent、如何做业务验收、如何打包部署模板,**不在本仓 roadmap 范围内**。
- 本仓不为消费仓的发布消费链路、demo 维护、acceptance 入口承担任务;只保证对外的协议、SDK、CLI、文档真源稳定可消费。

---

## 4. 兼容决策矩阵

| 决策点         | 当前锚点                                         | 长期约束                                                                        |
| -------------- | ------------------------------------------------ | ------------------------------------------------------------------------------- |
| 协议真源       | `anyagent.protocol.*` + schema bundle            | 可独立版本化的 protocol/spec 制品必须保持同一 semantic rules。                  |
| Server runtime | Python built-in server                           | 可替换 runtime 必须通过 reference conformance suite。                           |
| Client SDK     | Python SDK facade + TypeScript SDK scaffold      | 多语言 SDK 必须从 protocol/spec 派生并通过 contract fixtures。                  |
| 存储           | in-memory / SQLite / PostgreSQL / Redis adapters | 跨 runtime storage/replay contract 必须保持 session/run/event 语义一致。        |
| Tool Runtime   | 进程内与 standalone Tool Runtime contract        | manifest/execute、credential injection、policy enforcement 不绑定单一 runtime。 |
| Credential     | Env/File/Infisical backend + admin store         | Agent 只见 credential ref;secret 不通过 read API 回显。                         |
| Sandbox        | policy/backend adapter 分层                      | backend 可替换,agent loop 只消费 `exec` tool 与 sandbox policy。                |
| Multi-Agent    | runtime primitives 与 stage events               | parent/child/root run、quota 与 event replay 语义必须可验收。                   |

---

## 5. 分阶段路线

每个 Phase 只声明目标与对应 todo 入口,具体任务清单维护在 `todo/*.md`。

### 5.1 执行优先级与完成状态

> 最后更新：2026-05-30

#### 已完成(Phase 1 / 1.5 / 1.8 / 2)

Phase 1 ~ Phase 2 的主路径任务已全部完成。逐条任务历史见 Git 与各 `todo/*.md`,已实现能力的长期口径沉淀在架构文档:

| Phase | 已交付能力 | 架构文档锚点 |
| ----- | ---------- | ------------ |
| 1 | Protocol schema bundle 版本化、SDK conformance fixtures、TypeScript SDK 最小可用面 | `api/sdk-public-surface.md`、`api/sdk-compatibility-matrix.md`、`protocol-semantic-rules.md` |
| 1.5 | Tool Deferred Loading + Search、Skill 注入管道、三类 Replay(prompt context / tool execution / model request)、Plugin Manifest v1 + MCP filter、配置层级 merge + 热重载 + MCP 生命周期/会话池 | `tool-runtime/tool-runtime-contract.md`、`runtime/agent-packs-and-runtime-config.md`、`control-plane/studio-control-plane-and-observability.md`、`integrations/platform-connectors.md` |
| 1.8 | Sub-Agent 完整版、Agent Loop Middleware 4-hook 接口、上下文压缩、循环检测、Phase 1.8 Stage Events | `runtime/agent-loop-middleware.md`、`multi-agent/multi-agent-collaboration.md` |
| 2 | Tool Runtime contract 测试矩阵 + standalone 等价验收、Storage replay contract(PG+Redis)、跨节点 Run 调度与 lock contract、第二 sandbox backend、Unified Observability Sink | `tool-runtime/tool-runtime-contract.md`、`storage/storage-minimal-design.md`、`runtime/stateless-agent-service-architecture.md`、`runtime/sandbox-session-filesystem-design.md`、`decisions/`(run-scheduling-lock-contract、sandbox-backend-selection、storage-idempotency-and-cursor-semantics、observability-replay-sink-and-retention) |

#### Phase 3 / 4 已完成 + Phase 2.5 待启动

| 优先级 | #   | 任务                                       | Phase | 状态      | todo 入口                     |
| ------ | --- | ------------------------------------------ | ----- | --------- | ----------------------------- |
| **P4** | 21  | Credential v2 (DB/Vault/session/轮转/审计) | 3     | ✅ 已完成 | `todo/security-compliance.md` |
| **P4** | 22  | Multi-Agent contract（quota/replay contract） | 4  | ✅ 已完成 | `todo/multi-agent.md`        |
| **P4** | 23  | Reference conformance suite + Rust runtime PoC | 4 | ✅ 已完成 | `todo/multi-runtime.md`      |
| **P3** | 24  | Control-Plane Backend API（Sessions/MCP/Sandbox/Audit/Eval/Prompt 版本/Alert） | 2.5 | ✅ 已完成 | `todo/studio-backend.md` |

状态图例：🔲 未开始 · 🔵 进行中 · ✅ 已完成

依赖关系备注：

- #21 已完成 preview 实现；PostgreSQL schema 由 Alembic 管理，长期口径见 `docs/security/credential-vault.md`。
- #22 已完成 storage lock quota primitive 与 multi-agent replay contract；长期口径见 `docs/architecture/multi-agent/multi-agent-collaboration.md`。
- #23 已完成 reference conformance suite M1 补齐、Rust second-runtime ADR 与 PoC target；长期口径见 `docs/architecture/decisions/second-runtime-rust-reference.md`。
- #24 已完成 Sessions/MCP/Sandbox/Audit 查询面、Alert 后端、Evaluations/Dataset 后端与 Prompt 版本管理；长期口径见 `docs/architecture/control-plane/studio-control-plane-and-observability.md`。

> **决策记录（2026-05-29）**：当前仅公司内部使用，多租户/水平扩展需求推迟。Phase 2 中的分布式加固（#18 跨节点调度、#19 第二 sandbox backend）降为 P3，有外部用户需求后再投入。新增 Phase 1.8 聚焦内部高频需求：Sub-Agent、上下文压缩、循环检测、Middleware 接口。
>

> **决策记录（2026-05-29 技术调研）**：基于工作区仓库（Codex/DeerFlow/Pi-mono/OpenClaw/HiClaw）技术调研，Phase 1.8 新增 Middleware 接口（#14）作为框架扩展基础，循环检测和上下文压缩均作为内置 middleware 实现。Plugin Manifest v1（#9）扩展为含 middlewares/hooks 字段。详见 `docs/_notes/third-party/workspace-repos-tech-survey.md`。

---

### Phase 1 — Protocol & SDK Hardening(进行中)

**目标**:让 protocol bundle 与 SDK 成为对外可承诺兼容性的稳定面。

- 扩大 SDK conformance fixture 覆盖到 Responses API、Stage Events、Tool Runtime、storage replay 全主路径
- TypeScript SDK 从 scaffold 升级到最小可用(MVU)的 namespace 集合
- Protocol schema bundle 与 endpoint manifest 增加版本化策略与 changelog 出口

入口:[`todo/protocol.md`](../../../todo/protocol.md)、[`todo/sdk.md`](../../../todo/sdk.md)

需求锚点:`req-4`(SDK)、`req-4-1` ~ `req-4-6-2`(Responses API & SSE)、`req-7`(协议导出)

### Phase 1.5 — Agentic Ecosystem Hardening + Systematic Persistence

**目标**:双线并行——(1) 让 Tool Registry、Skill 系统、MCP 管理具备生产级注入与治理能力；(2) 让完整执行过程（prompt 组装、模型调用、工具执行）在 event store 中具备全量回放能力,支撑 Studio 历史回看、Eval/Replay 与审计。

Agentic Ecosystem:

- Tool Deferred Loading:引入工具曝光度分级（direct/deferred/hidden）与按需发现机制,减少 context token 浪费
- Skill → Agent Loop 注入管道:补齐 skill mention 解析 → SKILL.md 读取 → prompt context 注入的标准路径,带 token budget 控制
- Plugin Manifest v1 统一:升级 PluginManifest,一个 plugin 可同时声明 skills + mcp_servers + tools + middlewares + hooks。middlewares 字段为 Phase 1.8 Middleware 接口提供 plugin 侧注册能力
- 配置层级 merge:支持 system → user → workspace → session 的配置合并策略
- Config 热重载:mtime 轮询检测 agent.yaml/mcp.json 变更,热重载字段即时生效（参考 DeerFlow）
- MCP 生命周期事件:对齐 Stage Events 发射 MCP server 启动/就绪/失败状态
- MCP 会话池:按 (server_name, session_key) 池化 stdio 连接,LRU 淘汰（参考 DeerFlow）
- Plugin / Connector contract 公开化:统一 manifest schema + Gateway/Tool Runtime capability matrix + lifecycle hook 接入（见 `docs/architecture/decisions/plugin-connector-contract-v1.md` 与 `todo/tool-runtime.md`）

Systematic Persistence（系统性持久化）:

- Prompt Context Replay:rendered fragments 持久化 + 历史查询 API + Studio 展示
- Tool Execution Replay:tool input/output full payload 持久化 + 查询 API
- Model Request Replay:applied_body（注入 system/developer prompt 后的完整请求体）持久化 + replay API

入口:[`todo/tool-runtime.md`](../../../todo/tool-runtime.md)、[`todo/server-runtime.md`](../../../todo/server-runtime.md)、[`todo/persistence.md`](../../../todo/persistence.md)

需求锚点:`req-5`(Agent loop)、`req-5-2`(Tool Manifest)、`req-5-2-1`(Tool Registry)、`req-5-13`(Observability/Audit)、`req-6`(Gateway/Plugin)

### Phase 1.8 — Internal Productivity（内部生产力提升）

**目标**:让 AnyAgent 在公司内部场景中具备处理复合任务和长对话的能力,同时建立框架级扩展机制,快速提升内部团队的实际使用体验。

> 背景:当前仅公司内部使用,多租户/水平扩展暂不需要。本 Phase 聚焦内部高频需求。
> 技术调研:基于 Codex/DeerFlow/Pi-mono/OpenClaw/HiClaw 调研（`docs/_notes/third-party/workspace-repos-tech-survey.md`）。

核心交付：

- **Agent Loop Middleware 接口**:4-hook 设计（before/after model_call、before/after tool_execute），让循环检测、上下文压缩、审计等能力可配置、可替换、可组合。参考 DeerFlow middleware chain（精简）+ Pi-mono event-driven extension。
- **上下文压缩**:作为内置 middleware 实现。Codex handoff prompt 模板 + Pi-mono cut-point 选择算法（不在 tool chain 中间切断）+ 迭代式摘要更新（新摘要作为 UPDATE 生成）。通过 `agent.yaml` 配置阈值。
- **循环检测**:作为内置 middleware 实现。DeerFlow 算法直接移植：hash tool_calls → 滑动窗口(20) → 双阈值（warn 3 / hard stop 5）+ stable_tool_key 差异化。默认开启。
- **Sub-Agent 完整可用版**:在已有 `task()` tool + SubAgentExecutor 基础上补齐：并发限制（semaphore 默认 3）、超时（asyncio.wait_for 默认 15min）、深度限制（防递归）、fork mode（isolated / fork_last_n）、Stage Events 追踪（parent_run_id 关联）。
- **Phase 1.8 Stage Events**:Protocol 层新增 `subagent.spawned`/`subagent.completed`、`context.compacted`、`agent.loop_warning`/`agent.loop_terminated` event types。SDK + TypeScript SDK + conformance fixtures 同步。
- 嵌入 DeerFlow Skills:适配 `deep-research` 等不依赖沙箱的 skill,验证兼容性

入口:[`todo/multi-agent.md`](../../../todo/multi-agent.md)、[`todo/server-runtime.md`](../../../todo/server-runtime.md)、[`todo/sdk.md`](../../../todo/sdk.md)

需求锚点:`req-13`(multi-agent)、`req-5`(Agent loop)、`req-4`(SDK)

### Phase 2 — Production Runtime Hardening

**目标**:让 Python reference server 具备生产级 Tool Runtime 和存储验收能力。分布式多租户加固推迟到有外部用户需求时再投入。

- Tool Runtime standalone 模式 GA(manifest / execute / credential 注入 / policy 强制 contract 全通)
- Storage replay contract: PG + Redis 验收
- Unified Observability Sink:统一 envelope 出口格式,对接 OTel / 外部审计系统;Event Store 增加 TTL / retention policy
- （推迟）跨节点 Run 调度与 lock contract — 等有外部用户/多租户需求时再投入
- （推迟）Sandbox 第二 backend — 等有容器化部署需求时再投入

入口:[`todo/server-runtime.md`](../../../todo/server-runtime.md)、[`todo/storage.md`](../../../todo/storage.md)、[`todo/tool-runtime.md`](../../../todo/tool-runtime.md)、[`todo/sandbox.md`](../../../todo/sandbox.md)、[`todo/persistence.md`](../../../todo/persistence.md)

需求锚点:`req-3-1`(存储)、`req-5`(Agent loop & runtime)、`req-5-13`(audit)、`req-6`(Tool Runtime)、`req-12`(sandbox)

### Phase 2.5 — Control-Plane Backend（控制面后端 API）

**目标**:补齐 Studio 与 SDK 控制台消费的 server typed API。Studio 前端 16 页骨架已落地并消费现有 typed API,但从后端能力域看,运营态/治理态整片缺失——本 Phase 把这些控制面后端能力补全。前端页面设计是独立线,真源在 `packages/anyagent/studio/DESIGN.md`,不在本 Phase 范围。

> 背景:`/v1/responses`、agent catalog、tool/skill 治理、单 run observability 与三类 replay 已在 Phase 1.5 落地;本 Phase 聚焦控制面后端 API,而非前端组件。

按缺口性质分三组:

- **查询面缺失（数据已存在,开聚合查询出口,投入轻）**:
  - Sessions 编排查询面:`GET /internal/sessions` + `GET /internal/sessions/{key}`,按 `session_key` / `session_partition_key` 列会话与多 run 串联
  - MCP 管理 API:结构化 server 列表 + enablement 摘要 + 连接测试 + 运行态查询,替代整文件 `mcp.json` 回写
  - Sandbox / Workspace 运维 API:活跃 sandbox 列表、workspace 快照列表、强制回收,消费已有 lifecycle event
  - Audit 独立查询面:按 `credential_id` / `agent_id` / 时间窗查审计流水,与 observability errors 解耦
- **主动监控（新运行时机制,杠杆最高）**:
  - Alert 后端:alert rule 存储 + 后台评估器 + 订阅端点 + webhook fan-out;优先激活已在发的 `loop_warning` / `loop_terminated` 等信号
- **质量闭环与版本管理（新存储 + 逻辑,投入最重）**:
  - Evaluations / Dataset 后端:dataset 持久化 + 评测执行器 + 结果查询,替换 Studio 当前 localStorage-only 形态
  - Prompt 版本管理后端:版本快照 + diff + 回滚,与三类 replay 互补

当前状态：Phase 2.5 后端 API 已完成，证据与验证命令见 [`todo/studio-backend.md`](../../../todo/studio-backend.md)。

入口:[`todo/studio-backend.md`](../../../todo/studio-backend.md)

需求锚点:`req-14`(控制面后端)、`req-14-1` ~ `req-14-7`、`req-5-13`(observability/audit 数据源)

### Phase 3 — Security & Credential v2

**目标**:把现有 read-only credential 主路径升级到可承载企业合规的 vault 形态。

- DatabaseBackend(PostgreSQL 加密列)
- VaultBackend(HashiCorp Vault / AWS Secrets Manager 之一)
- Session 级临时凭据 scope(`CredentialScope.level=session`)
- 凭证轮转与过期(`expires_at` + `rotate_before`)
- 审计日志持久化(写入审计表,合规审查可查)

入口:[`todo/security-compliance.md`](../../../todo/security-compliance.md)

需求锚点:`req-8`、`req-5-13`

### Phase 4 — Ecosystem & Multi-Runtime

**目标**:让 anyagent 协议成为多语言、多 runtime 的事实标准。

- 第二 server runtime 实现(候选 Go 或 Rust),通过 reference conformance suite
- 多语言 SDK 按真实集成需求启动(候选 Go / Rust / Java),禁止空壳 scaffold
- Plugin / Connector 公开 contract 与一组参考实现
- Multi-Agent 编排原语 GA:在 Phase 1.8 MVP 基础上,补齐 parent/child/root run quota + event replay 全语义验收 + 跨 runtime 一致性

入口:[`todo/multi-runtime.md`](../../../todo/multi-runtime.md)、[`todo/sdk.md`](../../../todo/sdk.md)、[`todo/multi-agent.md`](../../../todo/multi-agent.md)

需求锚点:`req-7`(协议)、`req-13`(multi-agent)

### Phase 5 — 长期方向(尚未规划具体 todo)

- 协议独立版本化:把 `anyagent.protocol` 抽成可独立发布的制品,与 reference server 解耦
- Eval / Replay 平台化:把 event store + replay 升级为可审计的 agent eval 基础设施(以 Phase 2.5 的 Evaluations/Dataset 后端为前置,本阶段聚焦平台化与可审计性)
- 端侧形态评估:WebChat / 桌面 / IDE 插件;仅在 typed API 与 SDK 稳定后才进入主路径
- IM 渠道接入:飞书(Lark)为首选,后续可扩展 Slack / 钉钉;参考 DeerFlow channels 实现(见 `docs/_notes/third-party/deer-flow.md`)

这些方向在前置 Phase 完成前不开 todo,避免提前承诺。

---

## 6. Roadmap 维护规则

- 本文 Phase 级目标变更时,必须同轮更新对应 `todo/*.md` 入口。
- Phase 完成判定以 `todo/<module>.md` 全部条目收敛 + 对应 `docs/acceptance/` 验收脚本通过为准,不以代码合入数量为准。
- Out-of-scope 项(消费仓的事、市场需求未确认的兼容层、端侧 UI)在 Phase 5 之前不进 roadmap 主表。
