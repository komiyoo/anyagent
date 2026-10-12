# anyagent

anyagent 是一个**配置即服务**的 AI Agent Server 内核加 SDK。在 workspace 里写好 `AGENTS.md`、`agent.yaml`、`mcp.json` 和 skills，`anyagent serve` 一条命令就能启动一个兼容 OpenAI Responses API 的 Agent Server，不需要写服务端代码。

- PyPI distribution 与 Python import 包名：`anyagent`

## 设计理念

- **配置即服务**：agent 的行为、工具、技能、MCP server、沙箱和多 agent 边界都由 `.anyagent/` 下的配置文件描述，服务端代码由框架提供。
- **OpenAI 兼容优先，SDK 提供超集**：对外第一接口是 `POST /v1/responses` + SSE，任何 OpenAI SDK 都能直接接入；`AnyAgent` SDK 在此之上提供 tool/command 粒度的阶段事件（Stage Events）和查询、调试、管理接口。
- **协议先行**：`anyagent.protocol.*` 是所有 wire contract 的唯一真源。server、Python/TypeScript SDK 和 Studio 都从它派生，并导出 JSON Schema bundle 供其他语言和 runtime 使用。
- **资源可见，但不能直接操作**：agent 能看到可用的工具、技能和凭据引用，但密钥、凭据和工具策略由 server 代理。agent 只拿到 `credential_id`，由 server 解析并注入。
- **沙箱内自由，沙箱外隔离**：命令通过统一的 `exec` 工具在 per-session 沙箱中执行。沙箱策略和后端实现分开，后端可以替换（OpenSandbox / External / LocalUnsafe），agent loop 不需要知道用的是哪个后端。
- **无状态服务，事件可回放**：同一 `agent_id + session_key` 串行执行，不同会话并发互不干扰；事件 `seq` 单调递增，断线可按 `last_seq` 补发，请求支持幂等去重。
- **默认零外部依赖，按需扩展到生产**：开箱即用 in-memory 存储和进程内 Tool Runtime；PostgreSQL / MySQL / Redis / S3、独立 Tool Runtime、外部凭据后端通过 extras、插件和子命令按需启用。
- **可追溯**：从能力名能追到 tool manifest、协议模型、handler 和验收脚本，反过来也能从工具、事件追回所属能力。`tools.explain`、prompt 预览和插件目录让“为什么 agent 看得到这个工具”可以查询。

## 已实现模块

Python 包 `packages/anyagent/src/anyagent/`：

| 模块 | 内容 |
|---|---|
| `protocol` | Responses、Stage Events、Tool Runtime、Sandbox、Multi-Agent 等协议模型；导出 JSON Schema bundle 与 OpenAPI |
| `agent_runtime` | 基于 pydantic-ai 的 agent loop、prompt 组装与注入、模型 provider、多 agent 协作、scripted reply |
| `config` | 加载 `.anyagent/anyagent.yaml` 与 Agent Pack，处理配置分层合并和模型选择 |
| `skills` | 技能发现、加载、选择、依赖与权限，按需披露给 agent |
| `mcp` | MCP server 连接、鉴权、工具发现与 stdio 会话池 |
| `tool_runtime` | 工具注册、manifest/execute 契约、内置工具、CLI profile、独立 Tool Runtime 服务 |
| `plugins` | 插件 API 与 loader，内置 Chatwoot connector |
| `gateway` | 平台会话映射、agent 路由、connector 契约 |
| `storage` / `persistence` | Session / Run / Event / 幂等 / 锁存储；支持 in-memory、SQLite、PostgreSQL、MySQL、Redis |
| `server` | 内置 FastAPI Agent Server（`/v1/responses`、`/internal/*`、`/admin/*`）、分布式 runtime、沙箱后端、Credential Vault、Tool Policy |
| `AnyAgent` SDK（`agent_api_client` / `types`） | OpenAI 兼容面，以及 events、agents、tools、skills、prompts、observability、admin 命名空间 |
| `cli` | `anyagent` 命令行：workspace 初始化与检查、启动服务、存储迁移、凭据与插件管理；子命令见 `anyagent --help` |

仓库内其他部分：

| 路径 | 内容 |
|---|---|
| `packages/anyagent/studio/` | Studio 控制面（React/Vite），构建产物随 Python 包分发，由 `anyagent serve` 挂载 |
| `sdks/typescript/` | 从协议 schema 生成类型的 TypeScript client，供 Studio 使用，暂不发布 |
| `tools/anyagent-dev-cli/` | 本仓研发工具 CLI（版本提升、文档检查等） |

本仓不提供示例应用项目。业务方在自己的仓库里用 `anyagent init` / `anyagent config init` 生成骨架并自行部署，框架与业务仓库的分工见 [framework-boundary.md](docs/architecture/overview/framework-boundary.md)。

## 快速开始

```bash
pip install anyagent
anyagent init --workspace ./my-workspace
OPENAI_API_KEY=sk-... anyagent dev --workspace ./my-workspace
# API:    http://127.0.0.1:8787/v1
# Studio: http://127.0.0.1:8787/studio/
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="anyagent-dev-key")
response = client.responses.create(
    model="gpt-4o",
    input="hello",
    metadata={"agent_id": "main", "session_key": "demo"},
)
```

完整流程（模板、`agent.yaml` 配置、SDK、凭据与 MCP）见 [docs/guides/getting-started.md](docs/guides/getting-started.md)。

## 文档

- [docs/guides/](docs/guides/README.md)：使用指南
  - [getting-started.md](docs/guides/getting-started.md)：安装、生成 workspace、启动服务、调用接口
  - [deployment.md](docs/guides/deployment.md)：安装来源、部署形态、外置存储、观测、凭据后端、插件
- [docs/architecture/](docs/architecture/README.md)：架构设计，建议从 [system-components.md](docs/architecture/overview/system-components.md) 和 [roadmap.md](docs/architecture/overview/roadmap.md) 开始
- [docs/security/](docs/security/README.md)：威胁模型、沙箱、凭据管理、工具策略
- [docs/acceptance/](docs/acceptance/README.md)：验收入口
- [requirements.md](requirements.md)：需求与稳定锚点
- [todo/](todo/README.md)：工程任务
- [docs/release-checklist.md](docs/release-checklist.md)：发布流程
