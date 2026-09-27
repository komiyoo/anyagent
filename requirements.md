# anyagent 活跃需求索引

本文件不再承载已落地的长篇设计细节。已完成或已经稳定的内容沉淀到模块化文档：

- 架构真源：[docs/architecture/README.md](docs/architecture/README.md)
- 安全真源：[docs/security/README.md](docs/security/README.md)
- 验收真源：[docs/acceptance/README.md](docs/acceptance/README.md)
- 任务真源：[todo/README.md](todo/README.md)

保留本文件的目的：

- 为 `todo/*.md`、docs front matter 与代码注释提供稳定 `requirements.md#req-*` 锚点。
- 只记录尚未收敛为实现或长期文档的活跃需求。
- 指向已经模块化沉淀的设计文档，避免同一规则在多个地方重复维护。

## 0. 背景与目标

anyagent 是配置化、无服务化的 Agent Server Core + SDK。业务项目通过 `.anyagent/` 配置即可启动兼容 OpenAI Responses API 的 Agent Server，并可按需启用 SDK 精细事件、Tool Runtime、Sandbox、Credential Vault、Skills、MCP 与 Multi-Agent 能力。

<a id="0-1-仓库边界"></a>

### 0.1 仓库边界

仓库边界已经沉淀到：

- [docs/architecture/overview/apps-packages-boundary.md](docs/architecture/overview/apps-packages-boundary.md)
- [docs/architecture/decisions/single-repo-multi-package-boundary.md](docs/architecture/decisions/single-repo-multi-package-boundary.md)

口径：

- `anyagent` 是 Server Core、SDK、Protocol、production runtime、ops CLI、storage/tool/runtime/plugin contract 真源。
- `anyagent-apps` 是示例、模板、业务 workspace 与消费侧验收真源。
- 历史 `anyagent-apps/apps/*` 服务壳不再作为生产能力或兼容入口。

### 0.2 交付形态（配置即服务）

主路径是：

```bash
cd my-workspace && anyagent serve
```

工作区配置约定见：

- [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md)
- [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)

### 0.3 协议治理

- Wire 协议真源：`anyagent.protocol.*`
- SDK public typed facade：`anyagent.types`
- 公开 API、SSE event、Tool Runtime body、StageEvent、SandboxPolicy、session snapshot 等字段变化必须先回到 protocol/model 真源，再更新文档和验收。

## 1. 范围定义

### 1.1 In Scope

- 内置 Agent Server：`anyagent serve`、`POST /v1/responses`、SSE、agent loop、MCP、Tool Runtime、Sandbox、Session/Run/Event Store、Credential Vault。
- Client SDK：OpenAI 兼容面与 anyagent 精细面。
- 生产/分布式 contract：storage、lock、Tool Runtime service、Gateway/Connector、plugin、ops CLI。

### 1.2 Out of Scope（本阶段不做）

- 端侧 UI（WebChat/桌面端）。
- OpenAI ChatCompletions 兼容（`/v1/chat/completions`）。

### 1.3 Phase 分界

路线图见 [docs/architecture/overview/roadmap.md](docs/architecture/overview/roadmap.md)。Phase 2+ 能力可以先定义 contract，但不阻塞 Phase 1 主路径。

<a id="req-2"></a>

## 2. 核心概念与术语

术语和运行时实体分层见：

- [docs/architecture/runtime/agent-server-runtime-entities.md](docs/architecture/runtime/agent-server-runtime-entities.md)
- [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md)

<a id="req-2-1"></a>

### 2.1 Agent Packs（配置目录即行为包，开箱即用）

已沉淀到 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#agent-packs)。

<a id="req-2-1-1"></a>

#### 2.1.1 AGENTS.md 注入语义（v0 强制）

已沉淀到 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#agentsmd-注入语义) 与 [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)。

<a id="req-2-2"></a>

### 2.2 AgentSpec（agent.yaml）最小 schema（v0 强制）

已沉淀到 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#agentspec-agentyaml-最小-schema)。

## 3. 高层架构（组件边界）

架构入口见：

- [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)
- [docs/architecture/runtime/stateless-agent-service-architecture.md](docs/architecture/runtime/stateless-agent-service-architecture.md)

<a id="req-3-1"></a>

### 3.1 存储层（v0 最小设计）

已沉淀到 [docs/architecture/storage/storage-minimal-design.md](docs/architecture/storage/storage-minimal-design.md) 与 [docs/architecture/runtime/stateless-agent-service-architecture.md](docs/architecture/runtime/stateless-agent-service-architecture.md)。

<a id="req-4"></a>

## 4. 外部接口：OpenAI Responses API 兼容（Agent API）

已沉淀到：

- [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)
- [docs/architecture/decisions/openai-first-api-surface.md](docs/architecture/decisions/openai-first-api-surface.md)
- [docs/architecture/api/sdk-public-surface.md](docs/architecture/api/sdk-public-surface.md)

<a id="req-4-1"></a>

### 4.1 Endpoint

`POST /v1/responses` 是 OpenAI 兼容主入口；同步 SSE 与 SDK surface 设计见 [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)。

<a id="req-4-2"></a>

### 4.2 鉴权

`Authorization: Bearer <AGENT_API_KEY>` 与 `Idempotency-Key` 规则见 [docs/security/security-threat-model.md](docs/security/security-threat-model.md)。

<a id="req-4-3"></a>

### 4.3 会话标识（Session Key）

Session/Run/Event 与 `session_key` 规则见 [docs/architecture/runtime/agent-server-runtime-entities.md](docs/architecture/runtime/agent-server-runtime-entities.md)。

<a id="req-4-3-1"></a>

### 4.3.1 多 Agent（agent_id）选择与隔离

已沉淀到 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#agent_id-选择与隔离)。

<a id="req-4-4"></a>

### 4.4 Streaming 事件（SSE）

OpenAI 兼容 SSE 与 anyagent Stage Events 见：

- [docs/architecture/api/responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md)
- [docs/architecture/api/agent-api-client-stage-events.md](docs/architecture/api/agent-api-client-stage-events.md)

<a id="req-4-5"></a>

### 4.5 Tools（OpenAI function tools）

工具披露与执行以 Tool Runtime manifest/execute 为真源，见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md)。

<a id="req-4-6"></a>

### 4.6 会话恢复（Session Resume）与运行时配置绑定

已沉淀到 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#session-resume-与-runtime_config) 与 [docs/architecture/runtime/stateless-agent-service-architecture.md](docs/architecture/runtime/stateless-agent-service-architecture.md)。

<a id="req-4-6-1"></a>

#### 4.6.1 跨请求上下文恢复与首轮 input 组装

见 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#跨请求上下文恢复)。

部署者可通过 `runtime.scripted_reply_providers` 对已知输入返回确定性文本回复：命中时不调用模型，框架合成正常 Response 并走同一套 session snapshot 路径，使该轮进入后续上下文；可附可选的出站消息类型与属性，不含工具调用/handoff/多轮；以 `anyagent.response.scripted` 事件区分。见 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#runtimescripted_reply_providers)。

<a id="req-4-6-2"></a>

#### 4.6.2 会话运行参数绑定与 merge 更新

见 [docs/architecture/runtime/agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md#runtime_config-绑定与-merge-更新)。

<a id="req-4-7"></a>

### 4.7 Agent loop 实现与 tracing

Agent loop 由 pydantic-ai 执行；AnyAgent 保留托管面。自研 Event Store / Stage Events 仍是 SDK 消费渠道（写库）；Langfuse（OTLP）是附加渠道，未配置则关闭。Session/Run/Event 仍服务 resume 与协议补发。业务提示与策略留在消费侧 `.anyagent/`。见 [docs/architecture/decisions/pydantic-ai-loop-and-langfuse.md](docs/architecture/decisions/pydantic-ai-loop-and-langfuse.md)。

`runtime.middlewares` 的受信任 classpath 可返回 pydantic-ai `AbstractCapability`（包括 `Hooks`）；原生能力直接交给 pydantic-ai，兼容既有工具 middleware，不扩展自研 4-hook。业务侧可在模型请求前补充当轮约束、在模型答复交付前校验，非流式与 SSE 使用同一执行路径。

<a id="req-5"></a>

## 5. 内部接口：Tool Runtime

Tool Runtime contract 已模块化到 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md)。Skills 与 Tool Runtime 的交互见 [docs/architecture/skills/skills-tool-runtime-interaction.md](docs/architecture/skills/skills-tool-runtime-interaction.md)。

<a id="req-5-1"></a>

### 5.1 Tool Execute API

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#tool-execute-api)。

<a id="req-5-2"></a>

### 5.2 Tool Manifest

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#tool-manifest)。

<a id="req-5-2-1"></a>

### 5.2.1 Tool Registry 与热更新

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#tool-registry-与热更新) 与 [docs/architecture/decisions/tool-runtime-federation-v0.md](docs/architecture/decisions/tool-runtime-federation-v0.md)。

<a id="req-5-2-2"></a>

### 5.2.2 Manifest 缓存策略

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#manifest-缓存策略)。

<a id="req-5-3"></a>

### 5.3 工具分类与联邦式 Tool Runtime

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#工具分类与联邦式-tool-runtime) 与 [docs/architecture/decisions/tool-runtime-federation-v0.md](docs/architecture/decisions/tool-runtime-federation-v0.md)。

<a id="req-5-4"></a>

### 5.4 Tool Runtime 执行语义

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#执行语义)。

<a id="req-5-5"></a>

### 5.5 Sandbox 与命令执行

见 [docs/security/sandbox-security.md](docs/security/sandbox-security.md) 与 [docs/architecture/runtime/sandbox-session-filesystem-design.md](docs/architecture/runtime/sandbox-session-filesystem-design.md)。

<a id="req-5-6"></a>

### 5.6 Tool 命名规范

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#tool-命名规范)。

<a id="req-5-7"></a>

### 5.7 Tool Definition

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#tool-definition)。

<a id="req-5-8"></a>

### 5.8 `/internal/tools/execute` 请求体与响应体

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#internaltoolsexecute-字段契约)。

<a id="req-5-8-1"></a>

#### 5.8.1 Request

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#request-agent-api---tool-runtime-router)。

<a id="req-5-8-2"></a>

#### 5.8.2 Response

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#response-tool-runtime---agent-api)。

<a id="req-5-9"></a>

### 5.9 `context` 标准结构

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#context-标准结构)。

<a id="req-5-10"></a>

### 5.10 工具权限与策略

见 [docs/security/tool-policy.md](docs/security/tool-policy.md)。

<a id="req-5-11"></a>

### 5.11 幂等与去重

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#幂等与去重)。

<a id="req-5-12"></a>

### 5.12 取消语义

见 [docs/architecture/tool-runtime/tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md#取消语义)。

<a id="req-5-13"></a>

### 5.13 可观测性与审计

见 [docs/security/audit-logging.md](docs/security/audit-logging.md)。

<a id="req-6"></a>

## 6. Gateway：平台接入与消息交互

Gateway/Connector contract 已沉淀到：

- [docs/architecture/integrations/gateway-platform-routing.md](docs/architecture/integrations/gateway-platform-routing.md)
- [docs/architecture/integrations/platform-connectors.md](docs/architecture/integrations/platform-connectors.md)

Chatwoot 消息事件保留有效的 `message_id` / `message_type`，入站请求复用 `ChannelContext.message_id`；`anyagent.response.request` 记录可选的 `channel_context`（仅 `provider` / `message_id`），供消费者准确关联消息与处理轮次。旧事件缺少这些字段时，消费者不得把按时间窗口推算的结果当作精确关联。

<a id="req-6-1"></a>

### 6.1 插件化要求

见 [docs/architecture/integrations/platform-connectors.md](docs/architecture/integrations/platform-connectors.md)。

<a id="req-6-2"></a>

### 6.2 平台能力注入示例

见 [docs/architecture/integrations/gateway-platform-routing.md](docs/architecture/integrations/gateway-platform-routing.md#平台能力注入)。

<a id="req-6-3"></a>

### 6.3 会话/线程绑定策略

见 [docs/architecture/integrations/gateway-platform-routing.md](docs/architecture/integrations/gateway-platform-routing.md#会话线程绑定策略)。

<a id="req-6-4"></a>

### 6.4 多 Agent 的路由

见 [docs/architecture/integrations/gateway-platform-routing.md](docs/architecture/integrations/gateway-platform-routing.md#多-agent-路由)。

<a id="req-7"></a>

## 7. 并发与可靠性要求

并发分片、幂等、resume、backpressure、draining、断线补发与事件一致性已经沉淀到：

- [docs/architecture/runtime/stateless-agent-service-architecture.md](docs/architecture/runtime/stateless-agent-service-architecture.md)
- [docs/architecture/engineering/ci-pipeline.md](docs/architecture/engineering/ci-pipeline.md)
- [docs/performance/load-testing-baseline.md](docs/performance/load-testing-baseline.md)

<a id="req-8"></a>

## 8. 安全与合规

安全真源已经模块化到 [docs/security/README.md](docs/security/README.md)。

仍在 `todo/security-compliance.md` 跟踪的后续需求：

- P3 `[v2]` DatabaseBackend：PostgreSQL 加密列存储。
- P3 `[v2]` VaultBackend：HashiCorp Vault / AWS Secrets Manager。
- P3 `[v2]` session 级临时凭据 scope。
- P3 `[v2]` 凭证轮转与过期机制。
- P3 `[v2]` 凭证审计日志持久化。

<a id="req-9"></a>

## 9. 测试与验收标准

测试与验收真源已经沉淀到：

- [docs/acceptance/README.md](docs/acceptance/README.md)
- [docs/architecture/testing/testing-strategy.md](docs/architecture/testing/testing-strategy.md)
- [tests/README.md](tests/README.md)

<a id="req-9-1"></a>

### 9.1 Responses API 兼容性验收

见 [docs/acceptance/README.md](docs/acceptance/README.md) 与 [tests/acceptance/sdk/README.md](tests/acceptance/sdk/README.md)。

<a id="req-9-2"></a>

### 9.2 Gateway 端到端验收

消费侧验收入口在 `anyagent-apps/docs/acceptance/README.md`，Core 侧 connector contract 见 [docs/architecture/integrations/platform-connectors.md](docs/architecture/integrations/platform-connectors.md)。

## 10. 分期

当前分期说明见 [docs/architecture/overview/roadmap.md](docs/architecture/overview/roadmap.md)。工程任务以 [todo/README.md](todo/README.md) 为准。

## 11. 参考实现

参考实现只作为设计借鉴，不作为本仓 contract 真源。已保留的结论应沉淀在 `docs/architecture/**`、`docs/security/**` 或 `anyagent.protocol.*`。

<a id="req-12"></a>

## 12. AgentRuntime：Skills 加载与动态披露

Skills 动态披露已经模块化到：

- [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md)
- [docs/architecture/skills/skills-tool-runtime-interaction.md](docs/architecture/skills/skills-tool-runtime-interaction.md)
- [docs/architecture/decisions/skills-selection-policy.md](docs/architecture/decisions/skills-selection-policy.md)

<a id="req-12-1"></a>

### 12.1 Skill 包结构

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#skill-包结构)。

<a id="req-12-2"></a>

### 12.2 Skill Roots 与 Scope

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#skill-roots-与-scope)。

<a id="req-12-3"></a>

### 12.3 Skills Enable/Disable

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#skills-enabledisable)。

<a id="req-12-4"></a>

### 12.4 Skill Dependencies

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#skill-dependencies)。

<a id="req-12-5"></a>

### 12.5 Skill Permissions

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#skill-permissions)。

<a id="req-12-6"></a>

### 12.6 动态披露机制

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#动态披露机制)。

<a id="req-12-6-1"></a>

#### 12.6.1 选择技能

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#选择技能)。

<a id="req-12-6-2"></a>

#### 12.6.2 注入技能指令

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#注入技能指令)。

<a id="req-12-6-3"></a>

#### 12.6.3 披露工具

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#披露工具)。

<a id="req-12-7"></a>

### 12.7 内部 API：skills/list

见 [docs/architecture/skills/skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md#内部-api-skillslist)。

<a id="req-12-8"></a>

### 12.8 与 Tool Runtime 的交互关系

见 [docs/architecture/skills/skills-tool-runtime-interaction.md](docs/architecture/skills/skills-tool-runtime-interaction.md)。

<a id="req-13"></a>

## 13. Multi-Agent（Collab Agents）

Multi-Agent 设计已经模块化到：

- [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md)
- `docs/_dev/multi-agent/*`（仍在草案期的细节）

<a id="req-13-1"></a>

### 13.1 目标与非目标

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#目标与非目标)。

<a id="req-13-2"></a>

### 13.2 核心实体

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#核心实体)。

<a id="req-13-3"></a>

### 13.3 系统工具

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#系统工具)。

<a id="req-13-4"></a>

### 13.4 治理与限制

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#治理与限制)。

<a id="req-13-5"></a>

### 13.5 子 agent 与 tool/skills 的隔离策略

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#隔离策略)。

<a id="req-13-6"></a>

### 13.6 事件与审计

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#事件与审计)。

<a id="req-13-7"></a>

### 13.7 与 `/v1/responses` 的关系

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#与-v1responses-的关系)。

<a id="req-13-8"></a>

### 13.8 内部服务：AgentControl

见 [docs/architecture/multi-agent/multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md#agentcontrol)。

<a id="req-14"></a>

## 14. 控制面后端 API（Control-Plane Backend）

Studio 与 SDK 控制台消费的 server typed API。当前 `/v1/responses`、agent catalog、tool/skill 治理、单 run observability 与三类 replay 已落地（见 §4、§5、§12、§13）。本章只登记**尚未实现**的控制面后端能力：运营态查询面（Sessions）、配置面破洞（MCP 管理 API）、运维面盲区（Sandbox/Workspace ops）、合规查询面（Audit）、质量闭环后端（Evaluations/Dataset）、Prompt 版本管理与主动监控（Alert）。

口径约束：

- 这些都是 `/internal/*` 或 `/admin/*` typed endpoints，遵循 §0.3 协议治理——先回 `anyagent.protocol.*` 定义 wire model，再落 server handler 与 Studio 消费。
- 「查询面缺失」类（14.1/14.2/14.3/14.4）底层事件/数据已在 event store / telemetry / lifecycle event 中产生，只缺聚合查询出口；「需要新存储」类（14.5/14.6）与「需要新运行时机制」类（14.7）需要新增持久化模型或后台评估器。
- 长期设计口径落到 [docs/architecture/control-plane/studio-control-plane-and-observability.md](docs/architecture/control-plane/studio-control-plane-and-observability.md)，任务清单见 [todo/studio-backend.md](todo/studio-backend.md)。

<a id="req-14-1"></a>

### 14.1 Sessions 编排查询面

按 `session_key` / `session_partition_key` 列会话、看会话级聚合与一个会话内的多 run 串联。当前 Studio Sessions 页只能从 `/internal/observability/runs` 反推，缺 `GET /internal/sessions`（列表+过滤）与 `GET /internal/sessions/{key}`（会话详情+run 列表）。关联一等公民键见 `AGENTS.md §8`。

<a id="req-14-2"></a>

### 14.2 MCP 管理 API

结构化的 MCP server 列表、单 server enable/disable、连接测试与运行态查询。当前只能 `PUT /admin/workspace/agents/{id}/files/mcp_json` 整文件回写，`anyagent.mcp.server.{starting,ready,failed}` lifecycle event 已发但无查询面。需要 `GET /admin/workspace/agents/{id}/mcp/servers`（含 enablement 摘要）、连接测试端点与运行态查询。

<a id="req-14-3"></a>

### 14.3 Sandbox / Workspace 运维 API

生产运维所需的 sandbox/workspace 可见性与回收能力。`AnyAgentWorkspaceLifecycleEvent` 已覆盖 restore/checkpoint/hibernate，但缺 `GET /admin/sandboxes`（活跃列表）、`GET .../workspaces/{id}/snapshots`（快照列表）与强制回收/reclaim 端点。Sandbox 隔离面口径见 §5.5、[docs/architecture/runtime/sandbox-session-filesystem-design.md](docs/architecture/runtime/sandbox-session-filesystem-design.md)。

<a id="req-14-4"></a>

### 14.4 Audit 独立查询面

合规视角的审计流水查询，与「错误」解耦。当前 audit 数据只能从 `/internal/observability/errors`（`source=audit`）过滤。需要独立端点支持按 `credential_id` / `agent_id` / 时间窗查审计事件。审计语义真源见 §5.13、[docs/security/audit-logging.md](docs/security/audit-logging.md)。

<a id="req-14-5"></a>

### 14.5 Evaluations / Dataset 后端

把真实 run 转成可持久化、可回归、可团队共享的评测资产。当前 Studio Evaluations 页数据全在浏览器 localStorage，server 端零 eval/dataset 端点。需要 dataset 存储（CRUD）、`POST /internal/evaluations/run`（评测执行器）与结果存储/查询。这是 `AGENTS.md §2` 验证闭环支柱在产品层的落点。

<a id="req-14-6"></a>

### 14.6 Prompt 版本管理后端

prompt（AGENTS.md / skill 注入）的版本快照、diff 与回滚。当前只有 `/internal/prompt/bundle`（无状态预览）与单次 rendered prompt replay，缺「版本」概念。需要 prompt 版本快照存储 + `GET .../prompt/versions` + 版本 diff，与 §5.13 replay 互补（replay 逐字还原单次，本节管跨版本演进）。

<a id="req-14-7"></a>

### 14.7 监控告警（Alert）

把被动拉取式 observability 升级为主动监控。`anyagent.agent.loop_warning` / `loop_terminated`（runaway loop）等 stage event 已在发，但后端不存储告警状态、不暴露订阅端点。需要 alert rule 存储 + 后台评估器 + `GET /internal/observability/alerts` + webhook fan-out。监控数据源见 §5.13 与 stage events。
