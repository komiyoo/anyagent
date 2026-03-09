<!--
---
doc_kind: architecture
status: stable
tags: ["boundary", "anyagent", "anyagent-apps", "server-core", "security"]
summary: anyagent (Server Core + SDK) 与 anyagent-apps (高级部署 + 场景) 的职责边界与安全模型。
---
-->

# anyagent / anyagent-apps 职责边界

## 1. 总体定位

```text
┌─────────────────────────────────────────────────────────┐
│                anyagent (Server Core + SDK)              │
│                                                          │
│  "配置即服务"的 Agent Server 内核                         │
│  一条命令启动，零外部依赖                                  │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │protocol.*│ │agent_    │ │ skills.* │ │   mcp.*   │  │
│  │(协议SSOT)│ │runtime.* │ │(发现/选择)│ │(MCP管理)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────────┐   │
│  │gateway.* │ │tool_     │ │  server/ (内置)        │   │
│  │(会话/路由)│ │runtime.* │ │  ├─ Agent API         │   │
│  └──────────┘ │(工具注册)│ │  ├─ Tool Runtime      │   │
│               └──────────┘ │  ├─ in-memory store   │   │
│  ┌──────────────────────┐  │  └─ security/         │   │
│  │ AnyAgent Client SDK  │  └───────────────────────┘   │
│  └──────────────────────┘                               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│            anyagent-apps (高级部署 + 场景)                │
│                                                          │
│  消费 anyagent Server Core，扩展为生产级分布式部署         │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │ 高级部署模式                                    │      │
│  │ ├─ 分离式 Agent API (PG/Redis 持久化)           │      │
│  │ ├─ 独立 Tool Runtime (可横向扩缩容)             │      │
│  │ ├─ 分布式锁 / keyed serialization              │      │
│  │ └─ 事件补发 / rollout replay                   │      │
│  └───────────────────────────────────────────────┘      │
│  ┌───────────────────┐  ┌────────────────────────┐      │
│  │ 场景模板 & 示例    │  │ 平台 Connectors        │      │
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
| `tool_runtime.*` | 工具注册、client、plugin 模型 | `packages/anyagent/src/anyagent/tool_runtime/` |
| `agent_packs` | Agent Packs 配置加载与校验 | `packages/anyagent/src/anyagent/agent_packs.py` |
| `server/` | **内置 Agent Server**（FastAPI + in-memory store + 进程内 tool 执行） | `packages/anyagent/src/anyagent/server/` |
| `AnyAgent` SDK | Client SDK 资源型命名空间（openai/responses/events/skills） | `packages/anyagent/src/anyagent/agent_api_client.py` |
| CLI | `anyagent serve` / `anyagent agents list` / `anyagent tools list` | `packages/anyagent/src/anyagent/cli.py` |
| Security | Credential Vault / Tool Policy / Agent Sandbox 策略定义 | `packages/anyagent/src/anyagent/server/security/` |

**不做**：

- 不做 PG/Redis 持久化适配
- 不做分布式锁/跨实例 lease
- 不做平台 Gateway connector
- 不做 K8s/Helm 部署编排

### anyagent-apps — 高级部署 + 场景

**拥有（Owns）**：

| 模块 | 职责 | 路径 |
|---|---|---|
| 分布式 Agent API | PG/Redis 存储、分布式锁、事件补发、rollout replay | `apps/agent-api/` |
| 独立 Tool Runtime | 独立服务进程、HTTP manifest/execute、审计日志 | `apps/tool-runtime/` |
| 平台 Connectors | 飞书/Discord/TG 等平台消息桥接 | `plugins/` |
| 场景模板 | demo-workspace、multi-agent-team、project-template | `examples/` / `templates/` |
| 运维工具 | 数据迁移、保留策略、rollout replay CLI | `apps/*/storage/` |
| 应用层验收 | 在线 smoke / acceptance 脚本 | `tests/acceptance/` |

**不做**：

- 不重复实现协议模型（必须复用 `anyagent.protocol.*`）
- 不重复实现 agent loop 核心（必须复用 `anyagent.agent_runtime.*`）
- 不自定义 SDK client（必须使用 `AnyAgent`）

## 3. 收敛策略（Protocol-First）

1. 新增/修改任何协议（HTTP payload / SSE event / internal model）→ 先更新 `anyagent.protocol.*`
2. `anyagent.server/` 是内置 server 的参考实现，`anyagent-apps` 的分布式 server 消费相同的核心逻辑
3. 编排层差异（存储适配、分布式锁、平台 connector）属于"编排层特化"，不是重复实现

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
