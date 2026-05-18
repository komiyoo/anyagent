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

最快方式是用 `anyagent init` 生成一个最小可启动的 agent workspace：

```bash
anyagent init --workspace ./my-workspace --with-example-skill
anyagent doctor --workspace ./my-workspace
```

`init` 会生成一个最小可启动 workspace；`doctor` 会在启动前检查 agent pack、skills、MCP 配置和常见安全边界问题。`--with-example-skill` 会额外创建一个本地示例 skill，并把它加入默认选择。

常用参数：

```bash
# 指定 agent_id
anyagent init --workspace ./my-workspace --agent-id main

# 选择模板：basic | coding-agent | research-agent | multi-agent-team
anyagent init --workspace ./coding-workspace --template coding-agent

# 带示例 skill
anyagent init --workspace ./my-workspace --with-example-skill

# 覆盖本命令生成的已有文件
anyagent init --workspace ./my-workspace --force
```

`doctor --json` 输出遵循 typed protocol model（`WorkspaceDoctorReport`），可直接接入 CI 或平台控制面。

```text
my-workspace/
  AGENTS.md                       # workspace 级协作规范（可选）
  .agents/
    agents/
      main/                      # agent_id = "main"
        agent.yaml               # AgentSpec：工具、技能、多 agent 策略
        AGENTS.md                # agent 行为指令（注入到 prompt envelope）
        mcp.json                 # MCP server 连接配置（可选）
    skills/                      # 共享技能目录（可选）
      example-skill/
        SKILL.md                 # `--with-example-skill` 生成
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

### 2. 编辑 Agent 指令与配置

初始化后通常改这些文件：

```text
my-workspace/
  AGENTS.md
  .agents/agents/main/AGENTS.md
  .agents/agents/main/agent.yaml
  .agents/agents/main/mcp.json
```

`AGENTS.md` 写行为和协作方式，`agent.yaml` 控制工具、技能、沙箱和多 agent 边界，`mcp.json` 只放 MCP server 连接配置和凭证引用，不放明文 token。

一个最小 `AGENTS.md` 可以这样写：

```markdown
你是一个工作区内的 coding agent。

- 先理解用户目标，再选择工具。
- 执行命令前说明目的。
- 不要泄露凭据或环境变量。
- 修改文件后给出验证命令。
```

如果要启用命令执行，把 `agent.yaml` 中的 sandbox 打开，并让工具清单包含 `exec`：

```yaml
tools:
  requested_tool_names:
    - exec
sandbox:
  mode: "local-unsafe"   # 本地开发可用；生产建议接 opensandbox/external
```

### 3. 启动服务

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

# 结构化日志与第三方采集（可选）
ANYAGENT_LOG_FORMAT=json \
ANYAGENT_OBSERVABILITY_HTTP_URL=https://collector.example.com/ingest \
anyagent serve --workspace ./my-workspace
```

### 4. 调用 OpenAI 兼容接口

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

指定某个 agent 时，把 `agent_id` 放到 metadata，或者使用 `X-Agent-Id` header：

```python
response = client.responses.create(
    model="gpt-4o",
    input="用当前 workspace 的规则帮我检查项目",
    metadata={"agent_id": "main", "session_key": "demo-session"},
)
```

同一个 `agent_id + session_key` 会共享上下文并串行执行；不同 agent 或不同 session 会使用独立上下文分区。

### 5. 使用 anyagent SDK 查询与调试

```python
from anyagent import AnyAgent

client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="your-key")

# 健康检查
health = await client.health()
print(health.agent_ids)

# 查询当前允许外部指定的 agents
agents = await client.agents.list()
for item in agents.agents:
    print(item.agent_id, item.sandbox_mode, item.requested_tool_names)

# 查询某个 agent 的配置和 prompt 元信息
detail = await client.agents.get("main")
print(detail.agents_md.path, detail.agents_md.sha256, detail.agents_md.preview)

# 如确实需要完整 AGENTS.md 文本，显式打开 include_prompt
detail_with_prompt = await client.agents.get("main", include_prompt=True)

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

### 6. 配置凭据和 MCP

MCP server 或工具需要 token 时，不要把明文写进 `mcp.json`。先通过 Admin API 写入凭据引用：

```bash
ADMIN_API_KEY=admin-key anyagent credential set \
  --admin-url http://127.0.0.1:8787 \
  --admin-key admin-key \
  --id cred_bocha_mcp \
  --kind bearer_token \
  --scope agent \
  --agent-id main \
  --value-from-env BOCHA_MCP_TOKEN \
  --provider bocha
```

然后在 `.agents/agents/main/mcp.json` 中引用它：

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

也可以用 SDK 管理凭据：

```python
await client.admin.set_credential(
    {
        "credential_id": "cred_bocha_mcp",
        "kind": "bearer_token",
        "value": "...",
        "scope": {"level": "agent", "agent_id": "main"},
        "metadata": {"provider": "bocha"},
    }
)

creds = await client.admin.list_credentials()
await client.admin.delete_credential("cred_bocha_mcp")
```

### 7. 初始化模板和示例项目

当前仓库内的正式初始化入口是 `anyagent init`，内置以下 workspace 模板：

| 模板 | 适用场景 | 默认 agent | 默认工具/沙箱 |
|---|---|---|---|
| `basic` | 最小可启动 agent | `main` | 无工具，`sandbox.mode=disabled` |
| `coding-agent` | 本地代码理解、修改和验证 | `main` | `exec`，`sandbox.mode=local-unsafe` |
| `research-agent` | 资料检索、信息整理和来源归纳 | `main` | `core.web_fetch`，`sandbox.mode=disabled` |
| `multi-agent-team` | 一个 coordinator + 两个独立子 agent 的工作区骨架 | `main`、`researcher`、`coder` | coordinator 允许 spawn researcher/coder；coder 带 `exec` |

```bash
anyagent init --workspace ./basic-workspace --template basic --with-example-skill
anyagent init --workspace ./coding-workspace --template coding-agent
anyagent init --workspace ./research-workspace --template research-agent
anyagent init --workspace ./team-workspace --template multi-agent-team
```

`multi-agent-team` 当前生成的是多 Agent Pack 与 allowlist 骨架；完整的内建 spawn tool / child thread 编排还在演进中。它已经能作为多个上下文完全独立的 agent 配置模板使用，每个 agent 仍按 `agent_id + session_key` 分区。

初始化后可以用 SDK 查询这些 agent：

```python
agents = await client.agents.list()
for item in agents.agents:
    print(item.agent_id, item.spawn_allow_agent_ids)
```

如需手动扩展更多 agent，也可以复制已有 agent pack：

```bash
cp -R ./my-workspace/.agents/agents/main ./my-workspace/.agents/agents/researcher
anyagent doctor --workspace ./my-workspace
```

应用层 demo、生产级部署模板和平台 connector 会逐步放到同级项目 `anyagent-apps`；本仓库保持为 Server Core + SDK + Protocol 的真源。

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
      storage/                       # 共享存储模型/契约/replay/runtime 与 reference external adapters
        external/                    # SQL/Redis reference adapters、schema、migrations helper
      plugins/                       # Core 插件 API/loader/model
      server/                        # [内置] Agent Server（FastAPI + reference/external storage glue）
        migrations.py                # storage-migrate CLI glue
        sandbox/                     # Sandbox 后端（SandboxManager + Backend 实现）
        security/                    # Credential Vault / Tool Policy
      agent_packs.py                 # Agent Packs 配置加载
      agent_api_client.py            # Client SDK（AnyAgent 资源型命名空间）
      cli.py                         # CLI 入口（serve / init / doctor / storage-*）
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
│ ├─ 内置 Agent API │◄──────│ ├─ production wiring   │
│ ├─ 内置 Tool RT  │       │ ├─ 独立 Tool Runtime   │
│ └─ reference 存储 │       │ └─ 分布式锁/keyed seq │
│                  │       │                      │
│ SDK + Protocol   │       │ 场景模板 & 示例        │
│ ├─ AnyAgent      │       │ ├─ demo-workspace     │
│ ├─ protocol.*    │       │ ├─ multi-agent-team   │
│ ├─ storage.*     │       │ └─ project-template   │
│ └─ skills/mcp    │       │                      │
│                  │       │                      │
│ CLI (anyagent    │       │ 平台 Connectors       │
│  serve)          │       │ ├─ plugins/feishu     │
└──────────────────┘       │ └─ plugins/discord    │
                           └──────────────────────┘
```

- **anyagent**：电池内置的 Agent Server 内核 + SDK/Protocol + 共享服务语义层；包含 in-memory reference path，也包含 `storage.external` 的 typed SQL/Redis reference adapters 与迁移 helper。
- **anyagent-apps**：生产级部署 wiring、外置服务编排、独立 Tool Runtime、场景示例与平台 connector；不重复定义 Core 协议或 agent loop。

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
- **Agent Catalog API**：`GET /internal/agents` 列出当前允许外部指定的 agents，`GET /internal/agents/{agent_id}` 查看配置与 prompt 元信息；完整 prompt 文本需显式 `include_prompt=true`
- **SDK 控制面**：`client.health()`、`client.agents.*`、`client.tools.*`、`client.skills.*`、`client.prompts.*`、`client.admin.storage_health()`、`client.admin.tool_catalog()`、`client.admin.*_credential()` 与 `client.admin.*agent*()` 覆盖服务端 typed 管理/发现面
- **session_key**：平台侧线程/会话标识
- **session_partition_key**：并发分片键，固定为 `"{agent_id}::{session_key}"`
- **Skills 目录**：`.agents/skills/`（跨 agent 共享技能）
