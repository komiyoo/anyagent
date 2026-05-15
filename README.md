# anyagent — 配置化 Agent Server 内核 + SDK

anyagent 是一个**配置即服务**的 AI Agent 基础设施：通过 `AGENTS.md`、`agent.yaml`、`mcp.json` 等配置文件即可启动一个兼容 OpenAI Responses API 的 Agent Server，无需编写任何服务端代码。

```bash
cd my-workspace   # 包含 .agents/ 配置目录
anyagent serve     # 一条命令启动 Agent Server
```

## 核心特性

- **配置即服务**：通过 `.agents/` 目录定义 agent 行为、工具、技能、MCP server，零代码启动
- **OpenAI 兼容**：`POST /v1/responses` + SSE streaming，任意 OpenAI SDK 直接接入
- **细粒度观测**：anyagent SDK 提供 tool/command 级别的阶段性事件流（Stage Events）
- **安全边界**：Agent 只能"看到"和"使用"资源，不能"访问"和"操作"资源——密钥、凭证、tool policy 由 server 代理管理
- **零外部依赖启动**：内置 in-memory 存储 + 进程内 Tool Runtime，开箱即用
- **可扩展至生产级**：通过同级项目 `anyagent-apps` 扩展为 PG/Redis backend、独立 Tool Runtime、平台 Gateway 的分布式部署
- **共享服务层收敛**：Session / Run / Event / replay / resume 等共享语义应逐步回收到 Core，而不是长期散落在应用层

## 快速开始

### 1. 创建 workspace 配置

最快方式：

```bash
anyagent init --workspace ./my-workspace --with-example-skill
anyagent doctor --workspace ./my-workspace
```

`init` 会生成一个最小可启动 workspace；`doctor` 会在启动前检查 agent pack、skills、MCP 配置和常见安全边界问题。

```text
my-workspace/
  .agents/
    agents/
      main/                      # agent_id = "main"
        agent.yaml               # AgentSpec：工具、技能、多 agent 策略
        AGENTS.md                # 行为指令（注入到 system prompt）
        mcp.json                 # MCP server 连接配置（可选）
    skills/                      # 共享技能目录（可选）
```

**agent.yaml 示例**：

```yaml
exposed: true
tools:
  requested_tool_names:
    - core.web_fetch
    - exec                         # 启用命令执行（路由到沙箱）
skills:
  default_selected: []
sandbox:
  mode: "opensandbox"              # opensandbox | external | local-unsafe | disabled
multiagent:
  spawn_allow_agent_ids: ["main"]
```

**mcp.json 示例**：

```json
{
  "mcpServers": {
    "bocha-mcp": {
      "url": "https://mcp.bochaai.com/mcp",
      "transport": "streamable_http",
      "auth": {
        "credential_id": "cred_bocha_mcp",
        "ref_kind": "bearer_token",
        "injection": "header:Authorization",
        "format": "Bearer {value}"
      }
    }
  }
}
```

### 2. 启动服务

```bash
# 安装
uv pip install anyagent

# 启动（自动发现 .agents/ 配置）
anyagent serve --workspace ./my-workspace --port 8787

# 或使用环境变量
OPENAI_API_KEY=sk-... anyagent serve

# 使用外置存储（当前已支持 Session / Run / Event: PG 为主 + Redis 为热层）
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
REDIS_DSN=redis://127.0.0.1:6379/0 \
REDIS_NAMESPACE=anyagent \
POSTGRES_SCHEMA_POLICY=migrate \
STORAGE_MODE=external \
EVENT_STORE_BACKEND=external \
RUN_STORE_BACKEND=external \
SESSION_STORE_BACKEND=external \
EVENT_STORE_RETENTION_S=7200 \
RUN_STORE_RETENTION_S=7200 \
SESSION_STORE_RETENTION_S=86400 \
anyagent serve --session-lock-backend redis

# 运维自检
ADMIN_API_KEY=admin-key anyagent storage-health --admin-key admin-key

# 应用 PostgreSQL schema migration
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
anyagent storage-migrate

# 本地开发如需跳过显式 migration，可临时退回 runtime fallback
POSTGRES_SCHEMA_POLICY=runtime_create anyagent serve
```

### 3. 调用

```python
from openai import OpenAI

# 任何 OpenAI SDK 都可以直接连接
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="your-key")
response = client.responses.create(
    model="gpt-4o",
    input="帮我搜索一下最新的 AI Agent 框架",
    stream=True,
)
for event in response:
    print(event)
```

```python
from anyagent import AnyAgent

# anyagent SDK 提供细粒度观测
client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="your-key")

# OpenAI 兼容面
resp = client.openai.responses.create(model="gpt-4o", input="hello")

# anyagent 超集面：细粒度阶段性事件
async for event in client.events.stream_typed(resp.id):
    match event.type:
        case "anyagent.tool.planned":
            print(f"即将调用工具: {event.tool_name}")
        case "anyagent.tool.result":
            print(f"工具执行完成: {event.tool_name} ({event.status})")

# anyagent explain/debug 面
preview = await client.prompts.preview(
    {
        "model": "gpt-5",
        "input": "hello",
        "stream": False,
        "metadata": {"session_key": "sess_preview"},
    }
)

# 纯本地示例：不依赖真实服务端数据
example_bundle = client.prompts.example_run_bundle()
print(example_bundle.stage_events[0].type)

# 可切换不同 explain 模板场景
retry_bundle = client.prompts.example_run_bundle(scenario="toolset_retry")
research_bundle = client.prompts.example_run_bundle(scenario="multi_skill_research")

# 也可以先列出内置模板，再用 options 覆写局部特征
for item in client.prompts.example_scenarios():
    print(item.scenario, item.label)

custom_bundle = client.prompts.example_run_bundle(
    scenario="multi_skill_research",
    options={"include_mcp": False, "skill_count": 1, "sandbox_mode": "disabled"},
)
```

## 安全边界

anyagent 的核心安全原则：**沙箱内自由，沙箱外隔离**。

沙箱采用**策略-后端分离**架构（参考 Codex）：策略定义在 Protocol 层，后端可插拔（OpenSandbox / External / LocalUnsafe）。Agent 通过统一的 `exec` tool 执行命令，Tool Runtime 自动路由到配置指定的沙箱后端。同一 session 内的多次命令共享沙箱文件系统（per-session 隔离）。

| Agent 可以 | Agent 不可以 |
|---|---|
| 通过 `exec` tool 执行任意命令（`curl`、`python`、`git`） | 读取宿主机文件系统 / 环境变量 / 凭证原值 |
| 在沙箱中发起网络请求（访问外部网站、API） | 从沙箱访问 anyagent server / credential store |
| 在沙箱中读写文件、安装依赖（同 session 内持续） | 修改 agent.yaml / AGENTS.md 配置 |
| 看到可用 Skills / Tools / MCP Servers 列表 | 绕过 tool policy 执行未授权工具 |
| 通过 server 中介使用 API Keys（server 注入，agent 不见原值） | 访问其他 agent 的 session / credential |

## 项目结构

```text
anyagent/                            # 本仓库：Server Core + SDK
  packages/anyagent/
    src/anyagent/
      protocol/                      # 协议 SSOT（Responses/Tool Runtime/SSE/Multi-Agent）
        sandbox.py                   # Sandbox 策略模型（SandboxPolicy/NetworkSandboxPolicy/ResourceLimits）
      agent_runtime/                 # Agent loop 运行时（model providers/tool loop/prompt 注入）
      skills/                        # Skills 发现/加载/选择/权限
      mcp/                           # MCP server 管理（auth/连接/工具发现）
      gateway/                       # 会话映射/agent 路由/sequencer
      tool_runtime/                  # 工具注册/client/plugin
      server/                        # [内置] Agent Server（FastAPI + in-memory storage）
        sandbox/                     # Sandbox 后端（SandboxManager + Backend 实现）
        security/                    # Credential Vault / Tool Policy
      agent_packs.py                 # Agent Packs 配置加载
      agent_api_client.py            # Client SDK（AnyAgent 资源型命名空间）
      cli.py                         # CLI 入口（anyagent serve / agents / tools）
```

## 两层 API 输出

| 层级 | 协议 | 适用场景 |
|---|---|---|
| **OpenAI 兼容层** | `POST /v1/responses` + SSE | 任意 OpenAI SDK 直接接入；极简集成 |
| **anyagent 精细层** | `GET /internal/events/stream` → StageEvent | tool/command 粒度的阶段性结果；UI 进度展示、调试、审计 |

## 与 anyagent-apps 的关系

```text
anyagent (本仓库)           anyagent-apps (同级项目)
┌──────────────────┐       ┌──────────────────────┐
│ Server Core      │       │ 高级部署模式           │
│ ├─ 内置 Agent API │◄──────│ ├─ PG/Redis 持久化     │
│ ├─ 内置 Tool RT  │       │ ├─ 独立 Tool Runtime   │
│ └─ in-memory 存储 │       │ └─ 分布式锁/keyed seq │
│                  │       │                      │
│ SDK + Protocol   │       │ 场景模板 & 示例        │
│ ├─ AnyAgent      │       │ ├─ demo-workspace     │
│ ├─ protocol.*    │       │ ├─ multi-agent-team   │
│ └─ skills/mcp    │       │ └─ project-template   │
│                  │       │                      │
│ CLI (anyagent    │       │ 平台 Connectors       │
│  serve)          │       │ ├─ plugins/feishu     │
└──────────────────┘       │ └─ plugins/discord    │
                           └──────────────────────┘
```

- **anyagent**：电池内置的 Agent Server 内核 + 共享服务语义层
- **anyagent-apps**：生产级 backend/adapters + 分布式部署壳子 + 场景示例 + 平台 connector

## 文档

- [requirements.md](requirements.md) — 系统需求文档
- [docs/architecture/](docs/architecture/README.md) — 架构设计
  - [apps-packages-boundary.md](docs/architecture/apps-packages-boundary.md) — anyagent vs anyagent-apps 职责边界
  - [responses-api-sdk-and-server.md](docs/architecture/responses-api-sdk-and-server.md) — SDK + Server 泳道与模块边界
  - [roadmap.md](docs/architecture/roadmap.md) — Phase 1-4 演进路线图
  - [stateless-agent-service-architecture.md](docs/architecture/stateless-agent-service-architecture.md) — 无状态服务并发架构
  - [storage-minimal-design.md](docs/architecture/storage-minimal-design.md) — 存储最小设计
- [docs/security/](docs/security/README.md) — 安全设计
  - [credential-vault.md](docs/security/credential-vault.md) — 凭证管理
  - [sandbox-security.md](docs/security/sandbox-security.md) — Sandbox 安全边界
  - [tool-policy.md](docs/security/tool-policy.md) — 工具执行策略
- [todo/](todo/README.md) — 工程 TODO

## 关键约定

- **Agent Packs**：`.agents/agents/<agent_id>/` 目录即行为包（`agent.yaml` + `AGENTS.md` + `mcp.json`）
- **agent_id**：同一套服务内不同 agent 的标识（persona/权限/skills/tool policy 组合）
- **session_key**：平台侧线程/会话标识
- **session_partition_key**：并发分片键，固定为 `"{agent_id}::{session_key}"`
- **Skills 目录**：`.agents/skills/`（跨 agent 共享技能）
