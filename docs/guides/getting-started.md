<!--
---
doc_kind: guide
status: stable
tags: ["quickstart", "workspace", "cli", "sdk", "credential", "mcp"]
summary: 从零配置启动、初始化 workspace、单一 anyagent.yaml、到调用接口与迁移旧配置的上手流程。
audience: developer
req: ["requirements.md#req-0-2", "requirements.md#req-2-1"]
---
-->

# 快速上手

本文按顺序走一遍：安装 → 零配置启动 → 初始化与添加组件 → 理解配置文件 → 调用接口 → 配置凭据。生产部署与「只设环境变量」对照表见 [deployment.md](deployment.md)。

字段的完整列表以 `packages/anyagent/src/anyagent/config/schema.py` 的 `WorkspaceConfig` 为准。环境变量占位符以 `packages/anyagent/src/anyagent/config/defaults.py` 的 `builtin_defaults` 为准。查询方式见 [README.md](README.md#以代码为准)。

## 1. 安装

```bash
pip install anyagent
```

安装源与可选依赖见 [deployment.md](deployment.md#1-安装来源与可选依赖)。

## 2. 零配置启动

在任意目录：

```bash
OPENAI_API_KEY=sk-... anyagent serve
```

没有 `.anyagent/agents/` 时，服务使用内置 `main` agent。工作区根目录有 `AGENTS.md` 时，那段文字就是它的指令；没有则使用内置默认指令。默认模型别名是 `fast`（OpenAI `gpt-4o-mini`），`models.providers.openai.api_key` 读取 `OPENAI_API_KEY`。

默认监听 `127.0.0.1:8787`。未配置 `API_KEY` 时不校验调用方 token。`anyagent serve` 拒绝把非 loopback 地址（例如 `0.0.0.0`）和空的 API key 同时使用。`server.host` 不读取 `HOST`；`HOST` 只作用于独立 Tool Runtime。

```bash
# 本地开发：key 为空时使用 anyagent-dev-key，并尝试挂载 Studio
anyagent dev
```

## 3. 初始化、添加组件、检查

```bash
anyagent init --provider openai --model gpt-4o-mini
anyagent add tool echo
anyagent add skill review
anyagent add mcp docs
anyagent add agent reviewer
anyagent add plugin billing
anyagent config show --sources
anyagent doctor
```

- `init` 生成 `.anyagent/anyagent.yaml`、`.anyagent/schema/`、一个 agent 目录（`AGENTS.md` + 只写与默认不同的 `agent.yaml`）和工作区 `AGENTS.md`。与内置默认相同的模型不写入 yaml。不生成空的 `mcp.json`，也不生成示例插件。
- `--template` 可选 `basic`、`coding-agent`、`research-agent`、`multi-agent-team`。`--provider` 可选 `openai`、`anthropic`、`gemini`、`openai_chat`。`--agent-id` 不是 `main` 时额外生成一个 exposed 的 `main`。
- `add` 生成对应骨架，并登记到目标 agent 的 `agent.yaml` 或 `mcp.json`。tool / plugin 含 Python handler 与 `plugin.json`。
- `config show` 打印合并并插值后的配置，密钥脱敏。`--sources` 给出每个叶子来自哪一层、插值用了哪个环境变量。`credentials.runtime_env` 的每条绑定显示环境变量名和 `credential:<credential_id>`，不打印明文。
- `config schema` 导出 `anyagent.yaml`、`agent.yaml`、`mcp.json` 的 JSON Schema。`init` 把它写到 `.anyagent/schema/`，生成的 yaml 首行是 `# yaml-language-server: $schema=...`。
- `doctor` 在启动前检查 agent pack、skills、MCP 和常见安全问题。`--json` 可接入 CI。

## 4. 一个配置文件

工作区设置只在 `.anyagent/anyagent.yaml`。全部字段可省略。分段是 `models`、`server`、`storage`、`credentials`、`sandbox`、`plugins`、`observability`、`alerts`、`tool_runtime`。模型、服务、存储、凭据、沙箱、插件、观测、告警和 Tool Runtime 都在这里，不再使用仓库根目录的 `models.yaml` 或 `.anyagent/secrets.yaml`。

```yaml
# yaml-language-server: $schema=./schema/anyagent.schema.json
models:
  default: anthropic:claude-sonnet-4-5
credentials:
  backend: file
  writable: true
plugins:
  builtin: [chatwoot]
```

### 取值

唯一的取值写法是 `${VAR}` 和 `${VAR:-default}`。没有 `api_key_env` 这一类 `*_env` 字段。

- 未设置且没有默认时，占位符变成空字符串，随后该键被去掉，改用 schema 默认。
- `${VAR:-default}` 在变量未设置或为空时使用默认。默认值里可以再写占位符。
- 内置默认已经引用 `OPENAI_API_KEY`、`POSTGRES_DSN`、`API_KEY` 等约定变量，所以只导出环境变量、不写 yaml 仍然可用。对照表见 [deployment.md](deployment.md#3-只设环境变量)。

### 分层

低到高：内置默认 → system → user → workspace → CLI。

| 层 | 路径 |
|---|---|
| system | `$SYSTEM_CONFIG_DIR/anyagent.yaml`，默认 `/etc/anyagent/anyagent.yaml` |
| user | `$USER_CONFIG_DIR/anyagent.yaml`，默认 `~/.anyagent/anyagent.yaml` |
| workspace | `<workspace>/.anyagent/anyagent.yaml` |
| CLI | `serve` / `dev` 上显式传入的 flag |

同名字段后层覆盖前层。dict 递归合并，列表和标量整体替换。workspace 不能覆盖 system 或 user 已经设置的 `sandbox.mode` 和 `storage`；CLI 可以。实现是 `packages/anyagent/src/anyagent/config/loader.py` 的 `load_effective_config`。

### `.env`

进程启动时只加载一次工作区的 `.env`，再加载 `.env.local`。`.env.local` 覆盖 `.env` 里同名键。已经存在于进程环境中的键不会被覆盖。支持 `export ` 前缀、单引号、双引号，以及未加引号的值后面的 `#` 注释。加载器是 `packages/anyagent/src/anyagent/config/env.py` 的 `load_dotenv`。

## 5. Agent 的最小形态

`agent.yaml` 的每个字段都有默认值，文件可以不存在。一个 agent 目录可以只有 `AGENTS.md`。

`model` 只引用模型，不再写 provider、`api_key_env` 或 `base_url_env`：

```yaml
model: fast
# 等价于 model: {default: fast}
# 也可以写 provider:model，例如 anthropic:claude-sonnet-4-5
tools:
  requested_tool_names: [core.web_fetch]
```

解析顺序：请求里的 `model`，然后 agent 的 `model`，然后 `models.default`。别名优先于 `provider:model`。已知的 provider 前缀选择该 provider，其余字符串当作 OpenAI 上的模型名。别名和 provider 定义在 `models.aliases` / `models.providers`。

`exposed` 默认 `true`，`tools.requested_tool_names` 默认空列表。字段定义是 `packages/anyagent/src/anyagent/config/agents.py` 的 `AgentSpec`。目录约定、注入和 denylist 见 [agent-packs-and-runtime-config.md](../architecture/runtime/agent-packs-and-runtime-config.md)。

## 6. 调用接口

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="anyagent-dev-key")
response = client.responses.create(
    model="gpt-4o-mini",
    input="用当前 workspace 的规则帮我检查项目",
    metadata={"agent_id": "main", "session_key": "demo-session"},
)
```

未配置 API key 的 `serve` 不校验这个 token。`anyagent dev` 的默认 key 是 `anyagent-dev-key`。`agent_id` 也可以用 `X-Agent-Id` 传。同一个 `agent_id + session_key` 共享上下文并串行执行。

```python
from anyagent import AnyAgent

client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="anyagent-dev-key")
resp = client.openai.responses.create(model="gpt-4o-mini", input="hello")
```

SDK 命名空间见 [sdk-public-surface.md](../architecture/api/sdk-public-surface.md)。可运行示例：`tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py`。

## 7. 凭据与 MCP

凭据后端写在 `credentials`。`backend` 取 `none`、`env`、`file`、`db`、`vault`、`infisical`。可写性是 `writable`，不是后端名上的后缀。`runtime_env` 在启动时把列出的 credential 投影成进程环境变量，默认不覆盖已有值。

```yaml
credentials:
  backend: file
  writable: true
  file:
    root: ${CREDENTIAL_FILE_ROOT:-.anyagent/credentials}
  runtime_env:
    - name: OPENAI_API_KEY
      credential_id: openai
      kind: api_key
```

不启动 server、直接改本地后端：

```bash
anyagent credential set --local --workspace . \
  --id openai --kind api_key --scope global \
  --value-from-env OPENAI_API_KEY
```

省略 `--local` 时仍走 Admin API（`--admin-url` / `--admin-key`）。`mcp.json` 只引用 `credential_id`。后端语义见 [credential-vault.md](../security/credential-vault.md#34-运行时后端选择与能力查询)。

随包插件默认不加载。需要 Chatwoot 或 lifecycle echo 时在 `plugins.builtin` 里写 `chatwoot` 或 `lifecycle_echo`。

## 8. 从 0.4 配置迁移

0.5.0 不保留旧文件和旧字段。

| 旧写法 | 现在 |
|---|---|
| 仓库根 `models.yaml` | `.anyagent/anyagent.yaml` 的 `models:` |
| `.anyagent/secrets.yaml` | 同一文件的 `credentials:` |
| `base_url` 与 `base_url_env` 并存 | 只留值，写成 `${VAR}` 或 `${VAR:-default}` |
| `agent.yaml` 的 `model.provider` / `api_key_env` / `base_url_env` | `model: <别名>` 或 `model: provider:model` |
| `anyagent config init` | `anyagent init` |
| `anyagent storage-health` / `storage-migrate` / `storage-replay` / `storage-retention` | `anyagent storage health` / `migrate` / `replay` / `retention` |
| `MCP_CREDENTIAL_STORE_BACKEND`、`MCP_CREDENTIAL_STORE_FILE_ROOT`、`db-write` 这类带 `-write` 的名字 | `CREDENTIAL_BACKEND`、`CREDENTIAL_FILE_ROOT`，可写性用 `CREDENTIAL_WRITABLE` / `credentials.writable` |

设计原因见 [single-workspace-config.md](../architecture/decisions/single-workspace-config.md)。
