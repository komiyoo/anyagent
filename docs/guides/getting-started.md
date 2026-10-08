<!--
---
doc_kind: guide
status: stable
tags: ["quickstart", "workspace", "cli", "sdk", "credential", "mcp"]
summary: 从安装、初始化 workspace、编辑 Agent Pack、启动服务到用 OpenAI SDK 与 AnyAgent SDK 调用的上手流程。
audience: developer
---
-->

# 快速上手

本文按顺序走一遍：安装 → 生成 workspace → 编辑 agent 配置 → 启动服务 → 调用接口 → 配置凭据与 MCP。生产部署见 [deployment.md](deployment.md)。

本文只给每一步最常用的命令。参数、字段和默认值以代码为准，查询方式见 [README.md](README.md#以代码为准)。

## 1. 安装

```bash
pip install anyagent
```

安装源与可选依赖见 [deployment.md](deployment.md#1-安装来源与可选依赖)。

## 2. 生成 workspace

```bash
anyagent init --workspace ./my-workspace --with-example-skill
anyagent doctor --workspace ./my-workspace
anyagent agent list --workspace ./my-workspace
```

- `init` 生成一个最小可启动的 workspace；`--template` 可选 `basic`（最小 agent）、`coding-agent`（本地代码修改与验证）、`research-agent`（资料检索与整理）、`multi-agent-team`（一个 coordinator 加两个子 agent）。各模板生成的工具与沙箱配置见 `packages/anyagent/src/anyagent/cli.py` 的 `_init_agent_specs`。
- `doctor` 在启动前检查 agent pack、skills、MCP 配置和常见安全边界问题；`--json` 输出 typed 报告，可接入 CI。
- `agent list` 列出 workspace 里的 agent、工具、沙箱和 spawn 边界。

Agent Pack 的目录约定见 [agent-packs-and-runtime-config.md](../architecture/runtime/agent-packs-and-runtime-config.md#agent-packs)。`init` 还会生成一个 `plugins/demo/` 示例插件：它会被加载，但其工具默认不在任何 agent 的工具清单里，见 [tool-runtime-contract.md](../architecture/tool-runtime/tool-runtime-contract.md#内置工具与插件加载)。

### 业务仓库：`anyagent config init`

在业务仓库根目录一次生成 `models.yaml` 和 agent pack：

```bash
anyagent config init --workspace . --agent-id delivery-agent \
  --model-alias fast --model gpt-4.1-mini --provider openai --with-web-fetch
```

生成的 `agent.yaml` 里 `model.default: fast` 是一个别名，服务端按仓库根目录 `models.yaml` 解析成真实 provider 和模型名；请求体显式传 `model` 时优先使用请求值。`--agent-id` 不是 `main` 时会额外生成一个 exposed 的 `main` 作为默认入口。

## 3. 编辑 Agent Pack

| 文件 | 作用 |
|---|---|
| `AGENTS.md`（workspace 根目录） | workspace 级协作规范 |
| `.anyagent/agents/<agent_id>/AGENTS.md` | agent 的行为指令 |
| `.anyagent/agents/<agent_id>/agent.yaml` | 工具、技能、沙箱、默认模型、多 agent 边界 |
| `.anyagent/agents/<agent_id>/mcp.json` | MCP server 连接配置与凭据引用，不放明文 token |

`agent.yaml` 示例：

```yaml
exposed: true
tools:
  requested_tool_names: [core.web_fetch, exec]
sandbox:
  mode: local-unsafe        # 只用于可信的本地开发；生产用 opensandbox 或 external
multiagent:
  spawn_allow_agent_ids: [main]
```

- 字段定义以 `packages/anyagent/src/anyagent/agent_packs.py` 的 `AgentSpec` 为准，配置分层与 merge 规则见 [agent-packs-and-runtime-config.md](../architecture/runtime/agent-packs-and-runtime-config.md)。
- 只有 `exec` 这类命令执行工具需要开启沙箱，见 [sandbox-security.md](../security/sandbox-security.md)。
- 要给 agent 受控的命令行能力而不是裸 `exec`，用 `tools.cli` 定义 CLI profile，见 [tool-runtime-contract.md](../architecture/tool-runtime/tool-runtime-contract.md#cli-profile-工具)。

## 4. 启动服务

```bash
OPENAI_API_KEY=sk-... anyagent serve --workspace ./my-workspace --port 8787

# 本地开发：默认挂载 Studio，未配置 key 时使用 anyagent-dev-key
anyagent dev --workspace ./my-workspace
```

默认使用 in-memory 存储和进程内 Tool Runtime。外置存储与拆分部署见 [deployment.md](deployment.md)。

## 5. 调用 OpenAI 兼容接口

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="anyagent-dev-key")
response = client.responses.create(
    model="gpt-4o",
    input="用当前 workspace 的规则帮我检查项目",
    metadata={"agent_id": "main", "session_key": "demo-session"},
)
```

`agent_id` 也可以用 `X-Agent-Id` header 传。同一个 `agent_id + session_key` 共享上下文并串行执行，不同 agent 或会话相互隔离，见 [agent-packs-and-runtime-config.md](../architecture/runtime/agent-packs-and-runtime-config.md#agent_id-选择与隔离)。

## 6. 用 AnyAgent SDK 查询与调试

```python
from anyagent import AnyAgent

client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="anyagent-dev-key")
resp = client.openai.responses.create(model="gpt-4o", input="hello")

async for event in client.events.stream_typed(resp.id):   # tool/command 粒度的阶段事件
    print(event.type)

explain = await client.tools.explain("core.web_search", agent_id="main")  # 工具为什么可见/不可见
```

- 可运行的完整示例：`tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py`。
- 命名空间与公开模型见 [sdk-public-surface.md](../architecture/api/sdk-public-surface.md)，事件类型见 [agent-api-client-stage-events.md](../architecture/api/agent-api-client-stage-events.md)。

## 7. 配置凭据与 MCP

凭据通过 Admin API 写入，`mcp.json` 只引用 `credential_id`：

```bash
ADMIN_API_KEY=admin-key anyagent credential set \
  --admin-url http://127.0.0.1:8787 --admin-key admin-key \
  --id cred_bocha_mcp --kind bearer_token --scope agent --agent-id main \
  --value-from-env BOCHA_MCP_TOKEN
```

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

SDK 对应 `client.admin.set_credential()` / `list_credentials()` / `delete_credential()`，只返回引用，不返回明文。`anyagent serve` 默认把凭据存在内存里，重启即丢失；持久化后端见 [credential-vault.md](../security/credential-vault.md#34-运行时后端选择与能力查询)。

## 8. 多 Agent workspace

`multi-agent-team` 模板生成多个 Agent Pack 和 spawn allowlist 骨架，每个 agent 按 `agent_id + session_key` 独立分区；内建 spawn 工具和子线程编排仍在演进中，见 [multi-agent-collaboration.md](../architecture/multi-agent/multi-agent-collaboration.md)。手动加 agent 时可以复制已有 pack 目录，再跑一次 `anyagent doctor`。
