# anyagent — 配置化 Agent Server 内核 + SDK

anyagent 是一个**配置即服务**的 AI Agent 基础设施：通过 `AGENTS.md`、`agent.yaml`、`mcp.json` 等配置文件即可启动一个兼容 OpenAI Responses API 的 Agent Server，无需编写任何服务端代码。

PyPI distribution name: `anyagent`.
Python import package: `anyagent`.
Yunxiao Packages NPM package name: `anyagent`.

Public documentation: https://lyriktrip.mintlify.app/

## Install from Yunxiao Packages PyPI

```bash
pip install anyagent
```

Consumers should configure their package installer to read from the Yunxiao
Packages PyPI repository `anyagent`. Keep repository passwords in local,
server, or pipeline secrets, not in source-controlled dependency files.

## Package Source

Source code and release tags live in Codeup:
`https://codeup.aliyun.com/63d476f8d14a7f379aa798da/anyagent.git`.

The Yunxiao pipeline `4972656` (`anyagent build`) builds and verifies
`packages/anyagent/dist/` from Codeup, stores the built files as a Flow artifact,
and publishes them to the Yunxiao Packages PyPI repository when
`TWINE_PASSWORD` is configured as an encrypted pipeline variable. The same
pipeline verifies the TypeScript SDK from `sdks/typescript` and publishes it to
the Yunxiao Packages NPM repository `npm-registry` when npm credentials are
configured as encrypted pipeline variables. Detailed release steps live in
`docs/release-checklist.md`.

```bash
cd my-workspace   # 包含 .anyagent/ 配置目录
anyagent serve     # 一条命令启动 Agent Server
```

本地开发可用带默认 dev key 与启动信息的快捷入口：

```bash
anyagent dev --workspace ./my-workspace
# API:    http://127.0.0.1:8787/v1
# Studio: http://127.0.0.1:8787/ -> /studio/
```

## 核心特性

- **配置即服务**：通过 `.anyagent/` 目录定义 agent 行为、工具、技能、MCP server，零代码启动
- **OpenAI 兼容**：`POST /v1/responses` + SSE streaming，任意 OpenAI SDK 直接接入
- **细粒度观测**：anyagent SDK 提供 tool/command 级别的阶段性事件流（Stage Events）
- **安全边界**：Agent 只能"看到"和"使用"资源，不能"访问"和"操作"资源——密钥、凭证、tool policy 由 server 代理管理
- **零外部依赖启动**：内置 in-memory 存储 + 进程内 Tool Runtime，开箱即用
- **可扩展至生产级**：PG/MySQL/Redis、独立 Tool Runtime、Credential backend 与运维入口归属 Core，通过 extras、插件和子命令按需启用
- **共享服务层**：Session / Run / Event / replay / resume 等共享语义归属 Core，不由应用层重复维护

## 快速开始

### 1. 创建 workspace 配置

最快方式是用 `anyagent init` 生成一个最小可启动的 agent workspace：

```bash
anyagent init --workspace ./my-workspace --with-example-skill
anyagent doctor --workspace ./my-workspace
anyagent agent list --workspace ./my-workspace
```

`init` 会生成一个最小可启动 workspace；`doctor` 会在启动前检查 agent pack、skills、MCP 配置和常见安全边界问题；`agent list` 会列出 workspace 里的 agent、exposed 状态、sandbox、默认模型、工具和 spawn 边界。`--with-example-skill` 会额外创建一个本地示例 skill，并把它加入默认选择。初始化也会生成 `plugins/demo/` 插件示例代码，但不会默认启用：`app.demo.echo` 不会写入任何 agent 的 `requested_tool_names`，普通 `anyagent serve` 也不会自动加载 workspace plugin。

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
  models.yaml                     # workspace 级模型/provider 目录（可选）
  .anyagent/
    agents/
      main/                      # agent_id = "main"
        agent.yaml               # AgentSpec：工具、技能、多 agent 策略
        AGENTS.md                # agent 行为指令（注入到 prompt envelope）
        mcp.json                 # MCP server 连接配置（可选）
    skills/                      # 共享技能目录（可选）
      example-skill/
        SKILL.md                 # `--with-example-skill` 生成
  plugins/
    demo/                        # 默认生成但不启用的 Tool Runtime plugin 示例
      plugin.json
      plugin.py
      README.md
```

业务仓库根目录也可以用 `anyagent config init` 一次生成模型/provider 目录与 agent pack：

```bash
anyagent config init \
  --workspace ./my-workspace \
  --agent-id delivery-agent \
  --model-alias fast \
  --model gpt-4.1-mini \
  --provider openai \
  --with-web-fetch
```

这会生成业务仓库根目录 `models.yaml`、`.gitignore`、`.anyagent/agents/delivery-agent/*` 和默认不启用的 `plugins/demo/` 示例插件。如果 `--agent-id` 不是 `main`，还会同时生成一个 exposed `main` 默认入口，避免 `anyagent serve` 的默认入口缺失；业务调用仍可用 `metadata.agent_id=delivery-agent` 精确路由。

在 `.anyagent/agents/delivery-agent/agent.yaml` 中会写入：

```yaml
model:
  default: fast
```

`fast` 会在服务端解析为业务仓库根目录 `models.yaml` 里的真实 provider 与上游模型名。请求体显式传入 `model` 时仍优先生效，未传时使用 agent 的默认模型选择。

常用业务初始化开关：

```bash
# 采集/研究类 agent：开启内置网页抓取工具
anyagent config init --workspace ./research-workspace --agent-id reddit-collector --with-web-fetch

# 需要代码执行或本地命令的 agent：开启 exec，并默认写入 local-unsafe sandbox
anyagent config init --workspace ./ops-workspace --agent-id ops-agent --with-exec

# 显式声明工具或 sandbox
anyagent config init --workspace ./tool-workspace --agent-id worker --tool core.web_fetch --tool exec --sandbox-mode local-unsafe
```

`anyagent serve` 默认使用进程内 Tool Runtime，适合本地开发和单进程业务 demo；需要水平扩容、独立工具执行池或更强隔离时，再拆成 `anyagent agent-api serve` + `anyagent tool-runtime serve`。只有使用 `exec` 这类命令执行工具时才需要开启 sandbox；普通 `core.web_fetch` / MCP HTTP 工具不需要本地 sandbox。`local-unsafe` 只适合可信本地开发，生产建议接 `opensandbox` 或 `external`。

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
  .anyagent/agents/main/AGENTS.md
  .anyagent/agents/main/agent.yaml
  .anyagent/agents/main/mcp.json
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

# 如需外置存储，按 backend 安装可选依赖
uv pip install 'anyagent[postgres,redis]'
# 或：uv pip install 'anyagent[mysql,redis]'

# 启动（自动发现 .anyagent/ 配置）
anyagent serve --workspace ./my-workspace --port 8787

# 本地开发快捷启动：默认挂载 Studio，并在未配置 key 时使用 anyagent-dev-key
anyagent dev --workspace ./my-workspace

# 显示 agent pack 概览
anyagent agent list --workspace ./my-workspace

# 仅启动 API，不挂载 Studio
anyagent serve --workspace ./my-workspace --no-studio

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
ADMIN_API_KEY=admin-key anyagent storage health --admin-key admin-key

# 应用 PostgreSQL schema migration
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
anyagent storage migrate

# 本地开发如需跳过显式 migration，可临时退回 runtime fallback
POSTGRES_SCHEMA_POLICY=runtime_create anyagent serve

# 结构化日志与第三方采集（可选）
ANYAGENT_LOG_FORMAT=json \
ANYAGENT_OBSERVABILITY_HTTP_URL=https://collector.example.com/ingest \
anyagent serve --workspace ./my-workspace
```

内置 Studio 默认从 Core typed observability API 聚合运行数据，而不是读取日志文件或绑定某个日志后端。当前可通过 `/internal/observability/runs`、`/summary`、`/timeline`、`/metrics`、`/tools`、`/errors` 与 `/traces/{trace_id}` 查询 run 历史、工具性能、错误、trace/audit_ref 关联和聚合指标；结构化日志会同时进入 normalized telemetry store 与可选 HTTP collector。启用 `STORAGE_MODE=external` 且配置 `POSTGRES_DSN` 时，Core 会使用 PostgreSQL `telemetry_events` 表持久化 normalized telemetry events，支撑跨进程、跨重启的 Studio 查询；其他日志/分析后端暂不在本阶段接入。

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
from anyagent.types import AdminCredentialSetRequest

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

# 排查某个工具为什么对 agent 可见或不可见
tool_explain = await client.tools.explain("core.web_search", agent_id="main")
print(tool_explain.visible, tool_explain.requested_patterns, tool_explain.notes)

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

SDK 对外数据模型集中从 `anyagent.types` 导出；业务代码需要显式构造请求体时优先导入这些模型。`AnyAgent` 各命名空间方法会在请求发送前和响应返回后各做一次 Pydantic 边界校验，避免未校验的 dict 在业务层继续传播。

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

然后在 `.anyagent/agents/main/mcp.json` 中引用它：

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

`anyagent serve` 默认使用 Admin API 的 write-only 内存凭据库解析 MCP 引用；需要从环境变量、文件或 Infisical 读取 MCP 凭据时，可以设置 `MCP_CREDENTIAL_STORE_BACKEND=env|file|infisical`。`file` 后端默认读取 `<workspace>/.anyagent/credentials`；`infisical` 后端需安装 `anyagent[infisical]`，并配置 `INFISICAL_PROJECT_ID`、`INFISICAL_ENVIRONMENT`、`INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` 和 `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET`。独立 `anyagent tool-runtime serve` 的 process settings 由 `anyagent.tool_runtime.settings.ToolRuntimeSettings` / `ToolRuntimeServerConfig` 统一解析；它也可用同一变量解析凭据，需要 Tool Runtime credential store 的 `set/list_refs/delete` backend 时，可使用过渡模式 `env-write`、`file-write` 或 read-only `infisical-write`，并通过 `--admin-key` 或 `ADMIN_API_KEY` 启用 `/admin/credentials`。这些 resolver/admin-store 后端由 Core `anyagent.server.security.credential_runtime.CredentialRuntimeConfig` 统一组装。Core server 与 standalone Tool Runtime 都提供 `/admin/credentials/capabilities`，用于查看 resolver/admin-store、read-only 状态、required extras/env 与 planned db/vault 后端，不返回任何凭证明文。

独立 Tool Runtime 可通过 `--plugin-root` 或 `TOOL_RUNTIME_PLUGIN_ROOTS` 扫描包含 `plugin.json` 的插件目录，并使用 Core `anyagent.plugins` loader 与 `ToolRuntimePluginAPI` 将插件工具注册到统一 registry；加载失败默认 fail-closed，可用 `--plugins-fail-open` 或 `TOOL_RUNTIME_PLUGINS_FAIL_OPEN=1` 改为记录错误后继续启动。启用 `--admin-key` 或 `ADMIN_API_KEY` 后，`GET /admin/plugins/catalog`、SDK `client.admin.plugin_catalog()` 或 CLI `anyagent plugin catalog --admin-url <url> --admin-key <key>` 会返回 plugin roots、loaded plugin、registered tools、manifest/entrypoint cite、docs/schemas/tests refs 与 load errors，便于从工具追回插件来源。`anyagent init` / `anyagent config init` 生成的 `plugins/demo/` 只是脚手架示例；要让示例工具生效，需要启动独立 Tool Runtime 时传 `--plugin-root plugins`，并手动把 `app.demo.echo` 加入目标 agent 的 `tools.requested_tool_names`。

进程内与独立 Tool Runtime 都会从 Core `anyagent.tool_runtime.builtin_tools` 注册内置工具：`core.web_fetch`、`core.web_search`，以及需要显式 allowlist 的 privileged `admin.credential_set`。这些内置工具与插件工具一样进入统一 registry，并通过 `ToolDefinition.credentials` 解析 credential 到 handler context 的 `_credentials`，例如 `core.web_fetch` 可把 `bearer_token` 注入为 `Authorization` header，`core.web_search` 可把 `api_key` 注入给 Tavily / SerpApi provider。

独立 Tool Runtime 也提供本地 reference sandbox workspace 控制面：`GET /admin/sandbox/health`、`GET /admin/sandbox/workspaces`、`GET /admin/sandbox/workspace?agent_id=...&session_key=...`、`GET /admin/sandbox/events?agent_id=...&session_key=...`、`POST /admin/sandbox/workspace/hibernate` 与 `DELETE /admin/sandbox/workspace`。这些 endpoint 使用 Core `SandboxManager`、`anyagent.protocol.admin_storage` typed model 与 `anyagent.server.sandbox.workspace_events` event store，适用于 `sandbox.filesystem.persistence_mode=session_hot_cold` 的本地生命周期调试；设置 `WORKSPACE_EVENT_BACKEND=jsonl` 可把 workspace lifecycle events 写入本地 jsonl 以便重启后回放。Core 还提供 `anyagent.server.sandbox.workspace_snapshots` 的 local-file/S3-compatible snapshot store、`anyagent.server.sandbox.workspace_persistence` 的 local-file/Postgres workspace metadata store、in-memory/Redis workspace lease store 与 `hold_workspace_lease`、`anyagent.server.sandbox.opensandbox_backend.OpenSandboxWorkspaceBackend` 的 OpenSandbox Lifecycle API + execd proxy backend、`anyagent.server.sandbox.workspace_service.WorkspaceService` 的 restore/hibernate/delete/health 编排，以及 `anyagent.server.sandbox.workspace_runtime.build_workspace_runtime` 的 metadata/lease/snapshot/event/backend/service 组装器；`ToolRuntimeSettings` 会把 `ALLOW_SANDBOX`、`SANDBOX_*`、`WORKSPACE_*`、`POSTGRES_DSN`、`REDIS_DSN` 等 env 组装为 `WorkspaceRuntimeConfig`，`create_tool_runtime_app_async` 和 `anyagent tool-runtime serve` 会据此构造 `WorkspaceRuntimeAssembly`，让 standalone Tool Runtime 的 `exec` 和 admin sandbox endpoint 直接消费同一个 `WorkspaceService`。S3 需要安装 `anyagent[s3]`，Postgres/Redis workspace backend 需要对应 `anyagent[postgres]` / `anyagent[redis]` 可选依赖。

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
cp -R ./my-workspace/.anyagent/agents/main ./my-workspace/.anyagent/agents/researcher
anyagent doctor --workspace ./my-workspace
```

应用层 demo、生产级部署模板和平台 connector 由同级项目 `anyagent-apps` 消费；本仓库保持为 Server Core + SDK + Protocol 的真源。server、client SDK 与 Studio 继续在同一个仓库内协作，通过 protocol-first、多包边界和 contract tests 保持兼容；暂不拆成独立 repo。详细决策见 [single-repo-multi-package-boundary.md](docs/architecture/decisions/single-repo-multi-package-boundary.md)。

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
anyagent/                            # 本仓库：Server Core + SDK + Protocol + bundled Studio
  packages/anyagent/                 # 当前 Python distribution
    src/anyagent/
      protocol/                      # 协议 SSOT（Responses/Tool Runtime/SSE/Multi-Agent）
        sandbox.py                   # Sandbox 策略模型（SandboxPolicy/NetworkSandboxPolicy/ResourceLimits）
      agent_runtime/                 # Agent loop 运行时（model providers/tool loop/prompt 注入）
      skills/                        # Skills 发现/加载/选择/权限
      mcp/                           # MCP server 管理（auth/连接/工具发现）
      gateway/                       # 会话映射/agent 路由/sequencer
      tool_runtime/                  # 工具注册/client/plugin/standalone server
      storage/                       # 共享存储模型/契约/replay/runtime 与 reference external adapters
        external/                    # SQL/Redis reference adapters、schema、migrations helper
      plugins/                       # Core 插件 API/loader/model
      server/                        # [内置] Agent Server（FastAPI + reference/external storage glue）
        migrations.py                # storage-migrate CLI glue
        sandbox/                     # Sandbox 后端（SandboxManager + Backend 实现）
        security/                    # Credential Vault / Tool Policy
      agent_packs.py                 # Agent Packs 配置加载
      agent_api_client.py            # Client SDK（AnyAgent 资源型命名空间）
      cli.py                         # CLI 入口（serve / tool-runtime serve / init / doctor / storage）
    studio/                          # Studio React/Vite 源码，可独立 dev/build
  sdks/                              # 多语言 SDK 目录
    typescript/                      # 首个 scaffold：消费 protocol schema bundle
  tests/contract/                    # 协议/SDK/server 兼容契约
```

组织原则：

- `protocol/` 是 wire contract 真源；server、SDK、Studio 只消费它，不各自复制 shape。
- Python SDK 的业务模型从 `anyagent.types` 暴露；未来多语言 SDK 从同一份 spec/schema 生成基础模型，再补语言惯用 helper。
- Studio 只通过 OpenAI Responses API、`/internal/*` 与 `/admin/*` typed API 访问 Core；生产路径可继续由 `anyagent serve` 内嵌静态资源。
- 当 protocol/spec、SDK 兼容矩阵、发布节奏和 ownership 都稳定后，再评估是否拆出独立 repo。

## 两层 API 输出

| 层级 | 协议 | 适用场景 |
|---|---|---|
| **OpenAI 兼容层** | `POST /v1/responses` + SSE | 任意 OpenAI SDK 直接接入；极简集成 |
| **anyagent 精细层** | `GET /internal/events/stream` → StageEvent | tool/command 粒度的阶段性结果；UI 进度展示、调试、审计 |

## 与 anyagent-apps 的关系

```text
anyagent (本仓库)           anyagent-apps (同级项目)
┌──────────────────┐       ┌──────────────────────┐
│ 框架本体          │       │ 示例与模板             │
│ ├─ 内置 Agent API │◄──────│ ├─ production wiring   │
│ ├─ 内置 Tool RT  │       │ ├─ historical apps     │
│ ├─ 独立 Tool RT  │       │ └─ regression smokes   │
│ └─ reference 存储 │       │                      │
│                  │       │                      │
│ SDK + Protocol   │       │ 场景模板 & 示例        │
│ ├─ AnyAgent      │       │ ├─ demo-workspace     │
│ ├─ protocol.*    │       │ ├─ multi-agent-team   │
│ ├─ storage.*     │       │ └─ project-template   │
│ └─ skills/mcp    │       │                      │
│                  │       │                      │
│ CLI (serve /     │       │ 示例 Connectors       │
│  tool-runtime)   │       │ ├─ plugins/feishu     │
└──────────────────┘       │ └─ plugins/discord    │
                           └──────────────────────┘
```

- **anyagent**：框架本体，包含 Agent Server 内核、SDK/Protocol、共享服务语义层、基础生产 runtime、ops 入口、in-memory reference path，以及 `storage.external` 的 typed SQL/Redis reference adapters 与迁移 helper。
- **anyagent-apps**：示例与模板仓；不再承载历史 Agent API / Tool Runtime / Studio 服务壳，也不是 Core 协议、runtime、storage、Tool Runtime 或 ops CLI 的真源。

## 文档

- [requirements.md](requirements.md) — 活跃需求索引与稳定锚点；已完成设计沉淀在模块化 docs
- [docs/architecture/](docs/architecture/README.md) — 架构设计
  - [apps-packages-boundary.md](docs/architecture/overview/apps-packages-boundary.md) — anyagent vs anyagent-apps 职责边界
  - [single-repo-multi-package-boundary.md](docs/architecture/decisions/single-repo-multi-package-boundary.md) — server/client/studio 单仓多包边界与多语言 SDK 兼容策略
  - [responses-api-sdk-and-server.md](docs/architecture/api/responses-api-sdk-and-server.md) — SDK + Server 泳道与模块边界
  - [agent-packs-and-runtime-config.md](docs/architecture/runtime/agent-packs-and-runtime-config.md) — Agent Packs、AGENTS.md 注入、AgentSpec 与 session runtime config
  - [tool-runtime-contract.md](docs/architecture/tool-runtime/tool-runtime-contract.md) — Tool Runtime manifest/execute、registry、命名、context、幂等与取消
  - [sdk-public-surface.md](docs/architecture/api/sdk-public-surface.md) — AnyAgent SDK public surface、typed model facade 与验证入口
  - [roadmap.md](docs/architecture/overview/roadmap.md) — architecture direction 与当前架构锚点
  - [stateless-agent-service-architecture.md](docs/architecture/runtime/stateless-agent-service-architecture.md) — 无状态服务并发架构
  - [storage-minimal-design.md](docs/architecture/storage/storage-minimal-design.md) — 存储最小设计
  - [skills-dynamic-disclosure.md](docs/architecture/skills/skills-dynamic-disclosure.md) — Skills 动态披露
  - [gateway-platform-routing.md](docs/architecture/integrations/gateway-platform-routing.md) — Gateway 平台路由与 session 绑定
  - [multi-agent-collaboration.md](docs/architecture/multi-agent/multi-agent-collaboration.md) — Multi-Agent 编排与隔离
- [docs/security/](docs/security/README.md) — 安全设计
  - [credential-vault.md](docs/security/credential-vault.md) — 凭证管理
  - [sandbox-security.md](docs/security/sandbox-security.md) — Sandbox 安全边界
  - [tool-policy.md](docs/security/tool-policy.md) — 工具执行策略
- [todo/](todo/README.md) — 工程 TODO

## 关键约定

- **Agent Packs**：`.anyagent/agents/<agent_id>/` 目录即行为包（`agent.yaml` + `AGENTS.md` + `mcp.json`）
- **agent_id**：同一套服务内不同 agent 的标识（persona/权限/skills/tool policy 组合）
- **Agent Catalog API**：`GET /internal/agents` 列出当前允许外部指定的 agents，`GET /internal/agents/{agent_id}` 查看配置与 prompt 元信息；完整 prompt 文本需显式 `include_prompt=true`
- **SDK 控制面**：`client.health()`、`client.agents.*`、`client.tools.*`、`client.skills.*`、`client.prompts.*`、`client.admin.storage_health()`、`client.admin.tool_catalog()`、`client.admin.plugin_catalog()`、`client.admin.*_credential()` 与 `client.admin.*agent*()` 覆盖服务端 typed 管理/发现面
- **session_key**：平台侧线程/会话标识
- **session_partition_key**：并发分片键，固定为 `"{agent_id}::{session_key}"`
- **Skills 目录**：`.anyagent/skills/`（跨 agent 共享技能）
