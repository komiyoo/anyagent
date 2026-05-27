<!--
---
doc_kind: architecture
status: stable
tags: ["roadmap", "phases", "anyagent", "anyagent-apps"]
summary: anyagent 四阶段演进路线图，从极简 serve 到平台化企业级。
---
-->

# anyagent 演进路线图（Roadmap）

## 总体愿景

anyagent 的目标是成为**配置化、无服务化**的 AI Agent 基础设施：

- **极简版本**：`anyagent serve` 一条命令，兼容 OpenAI Responses API
- **精细版本**：anyagent SDK / Client 提供 tool/command 级别的细粒度阶段性结果
- **核心原则**：Agent 只通过 `AGENTS.md` / `agent.yaml` / `mcp.json` 配置启动服务；Agent 可见资源但不可直接操作资源

---

## Phase 1：极简 `anyagent serve`（内核收敛）

**目标**：一条命令从配置启动 agent server，兼容 OpenAI Responses API，零外部依赖。

```bash
cd my-workspace && anyagent serve
```

### 关键任务

#### 1.1 `anyagent.server` 模块

核心 agent loop 编排已收敛到 `anyagent.server/`：

- FastAPI app + `POST /v1/responses` + SSE streaming
- 进程内 Tool Runtime（manifest + execute，无需启动独立服务）
- In-memory Session / Run / Event Store（零外部依赖）
- Agent Packs 自动发现与路由
- MCP 连接池管理

#### 1.2 CLI 入口

- `anyagent serve --workspace . --port 8787` — 启动 server
- `anyagent init --workspace ./my-workspace` — 生成最小可配置 workspace
- `anyagent doctor --workspace ./my-workspace` — 校验 workspace 配置与安全边界
- `anyagent storage health` — 检查内置 server 存储后端与连通性
- `anyagent storage migrate` — 应用 PostgreSQL / SQL backend schema

说明：

- 旧版本草案里曾写过 `anyagent agents list` / `anyagent tools list`，当前仓库主 CLI 不再提供这两个子命令。
- agent / tool 的 typed 发现面已转为 SDK 的资源型 namespace 与 `/internal/*` / `/admin/*` 发现接口。

#### 1.3 Sandbox 执行（策略-后端分离架构）

采用**策略-后端分离**架构（参考 Codex 的 `SandboxPolicy` + `SandboxManager::transform()` 分层），默认集成 [OpenSandbox](https://github.com/alibaba/OpenSandbox) 作为沙箱后端：

- **Protocol 层策略**：`SandboxPolicy` / `NetworkSandboxPolicy` / `ResourceLimits`，定义在 `anyagent.protocol.sandbox`
- **可插拔后端**：`OpenSandboxBackend`（默认）/ `ExternalSandboxBackend`（K8s Pod 即沙箱）/ `LocalUnsafeBackend`（开发模式）
- **会话隔离**：per-session sandbox，同 session 内多次 `exec` 共享文件系统（有状态工作流）
- **运行时无感**：agent loop 只调用 `exec` tool，不感知沙箱后端
- **配置驱动**：`agent.yaml` 的 `sandbox.mode` 决定后端选择
- **统一命令入口**：`exec` tool（core 类别），不封装为 `sandbox.*` 工具命名空间
- 沙箱内 Agent 自由度：执行命令、发起网络请求、读写文件、安装依赖
- 沙箱外隔离：不挂载凭证、egress 策略阻止内部访问
- 隔离等级可选：Docker (runc) / gVisor / Kata / Firecracker

#### 1.4 Credential Vault（安全边界 v1）

- `mcp.json` 中的 `credential_id` → 从环境变量 / `.env` 解析
- Agent 只见 `credential_id`，server 负责注入
- 只有 `set`，没有 `get`

#### 1.5 anyagent-apps 反向消费

- `anyagent-apps` 的 agent-api 改为消费 `anyagent.server` 的核心逻辑
- 仅补充 PG/Redis 存储适配、分布式锁等生产级能力
- 避免两处代码分叉

#### 1.6 Storage / 外置后端边界

- Core 已包含共享存储契约、reference runtime bundle 与 `storage.external` typed adapter。
- 生产级 PostgreSQL / Redis wiring、分布式锁、保留策略和 rollout/replay 运维入口仍由 `anyagent-apps` 承担。

### 交付物

- [x] `anyagent serve` CLI 可用
- [x] `POST /v1/responses` + SSE 兼容 OpenAI SDK
- [x] Agent Packs 配置即服务
- [x] 进程内 Tool Runtime + MCP 集成
- [x] OpenSandbox 沙箱集成（策略-后端分离、会话隔离、exec tool）
- [x] Credential 环境变量注入

---

## Phase 2：Client SDK 细粒度结果 + 安全加固

**目标**：anyagent SDK/Client 提供比 OpenAI SDK 更丰富的中间过程观测，安全模型加固。

### 关键任务

#### 2.1 Stage Events 完善

- `anyagent.tool.planned` / `anyagent.tool.result` — 工具级
- `anyagent.command.planned` / `anyagent.command.result` — 命令级
- `anyagent.skill.activated` — 技能级
- `anyagent.mcp.tool.invoked` / `anyagent.mcp.tool.result` — MCP 工具级

#### 2.2 AnyAgent Client 增强

- 已落地 `client.events.stream_typed()`、`client.events.list_typed()`、`client.events.latest_prompt_context()` 与 `client.events.replay_summary()`。
- 已补齐 resource namespace：`client.agents`、`client.skills`、`client.tools`、`client.prompts`、`client.observability`、`client.admin` 与 `client.health()`。
- SDK public model facade 已集中到 `anyagent.types`；模块归属、公开 surface 与验证入口见 [sdk-public-surface.md](sdk-public-surface.md)。
- 断线续传主路径使用 `last_seq` / `next_last_seq`，并由 internal events list/stream 共享序号语义。

#### 2.3 安全加固

- Tool policy enforcement（白名单/黑名单/审批流）
- Credential 分级（agent 级别隔离）
- Audit logging（结构化审计日志，不含敏感值）
- Sandbox egress 策略精细化（per-agent 网络规则）
- Sandbox 资源配额治理（per-agent CPU/内存/磁盘限制）

#### 2.4 MCP Server 热管理

- 运行时 MCP 连接池
- MCP server 健康检查与重连
- MCP tool 动态发现

### 交付物

- [x] Stage Events 覆盖 prompt context、model stream、tool planned/result、command planned/result 与 done 主路径
- [x] `client.events.stream_typed()` / `list_typed()` / replay helpers 可用
- [x] SDK public model facade 与 control-plane namespace 可用
- [ ] Tool policy + credential scope 继续完善
- [ ] Audit logging 结构化输出继续完善

---

## Phase 3：多 Agent 编排 + 生态

**目标**：支持 multi-agent 协作，skills 生态扩展。

### 关键任务

#### 3.1 Multi-Agent

- `spawn/send/wait/close` 原语
- Agent 间通信（共享 context 或 message passing）
- 资源配额治理（depth limit / concurrent limit）
- Thread 管理（parent/child/root）

#### 3.2 Skills 生态

- Skills marketplace / registry
- Skills 版本管理与依赖推导
- 动态 skills 发现（runtime hot-reload）
- Skills 权限模型（sandbox 能力上限）

#### 3.3 anyagent-apps 高级部署增强

- 分布式 Agent API（PG + Redis + keyed serialization）
- Tool Runtime Federation（remote executors）
- K8s Helm chart + 自动扩缩容

### 交付物

- [ ] Multi-Agent spawn/send/wait/close 完整
- [ ] Skills 动态发现与版本管理
- [ ] Helm chart 可用

---

## Phase 4：平台化 + 企业级

**目标**：企业级多租户、管理后台、安全沙箱。

### 关键任务

#### 4.1 平台 Gateway

- 平台 connector contract 真源在 `anyagent.plugins`；具体平台实现优先采用官方包或独立 optional connector，当前状态见 [platform-connectors.md](platform-connectors.md)
- 飞书 / Discord / Telegram / Slack connector 完善
- 统一消息桥接协议
- 平台能力注入（群信息、文档操作等）

#### 4.2 多租户

- `tenant_id` 激活，全链路租户隔离
- 租户级 Agent / Credential / Policy 配置
- 计量与配额

#### 4.3 管理后台

- Agent CRUD API
- 运行时监控（active runs / tool calls / errors）
- 日志查询与审计报告

#### 4.4 Sandbox Executor

- 独立隔离沙箱（v8 / wasm / docker container）
- 资源限制（CPU / memory / network / filesystem）
- 安全审计与合规

### 交付物

- [ ] 多租户隔离
- [ ] 管理后台 API
- [ ] Sandbox executor 可用
- [ ] 4+ 平台 connector optional packages

---

## Phase 间的关键架构决策

| 决策点 | Phase 1 | Phase 2+ |
|---|---|---|
| 存储 | in-memory（零依赖） | 可选 SQLite → PG/Redis |
| Tool Runtime | 进程内执行 | 可拆为独立服务 |
| Credential | EnvBackend | FileBackend → VaultBackend |
| Sandbox | OpenSandboxBackend + per-session 隔离 + exec tool | ExternalSandboxBackend (K8s) + gVisor/Kata + 精细 egress |
| Multi-Agent | 基础 spawn | 完整 lifecycle |
| 部署 | 单进程 | Docker Compose → K8s |
| 安全 | Tool policy + env credential + sandbox 隔离 | Audit + scope isolation + 资源配额 |
