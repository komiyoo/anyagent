# Demo 应用定制化验收与使用说明（apps/*）

对应需求：`requirements.md#req-2`、`requirements.md#req-5`、`requirements.md#req-12`

目标：把 `apps/agent-api` + `apps/tool-runtime` 当作一个可运行 demo，验证“可定制化能力”在应用层可直接落地，而不是只停留在协议设计。

## 1. 覆盖的定制能力

- Agent Packs：按 `agent_id` 装载独立行为包（`agent.yaml + AGENTS.md`）
- Skills：按请求/默认策略/显式 mention 选择并注入
- Tool Runtime 插件：通过 `TOOL_RUNTIME_PLUGIN_ROOTS` 动态加载工具
- 凭证注入：通过 Credential Store + Admin API 管理工具凭证
- 会话隔离：同一 `session_partition_key = {agent_id}::{session_key}` 的串行一致性

## 2. 环境准备

推荐：使用 demo 默认配置模板，复制后直接替换即可（避免逐条 `export`）：

```bash
cp apps/tool-runtime/.env.example apps/tool-runtime/.env
cp apps/agent-api/.env.example apps/agent-api/.env

# 然后编辑 apps/agent-api/.env（至少替换 OPENAI_API_KEY）
```

初始化 demo workspace（Agent Packs/skills）：

```bash
mkdir -p .runs
cp -R examples/demo-workspace .runs/demo-workspace
```

（可选）如果你希望继续使用 `export ...` 方式，也可以按下面设置：

```bash
export TOOL_RUNTIME_INTERNAL_KEY="dev-internal-key"
export AGENT_API_KEY="dev-agent-api-key"
export OPENAI_API_KEY="<YOUR_OPENAI_KEY>"
export WORKSPACE_DIR="$PWD/.runs/demo-workspace"
```

可选（开启插件与 admin）：

```bash
export TOOL_RUNTIME_PLUGIN_ROOTS="$PWD/plugins"
export ADMIN_API_KEY="dev-admin-key"
```

初始化 demo workspace：

```bash
mkdir -p "$WORKSPACE_DIR/.agents/agents/demo-assistant"
mkdir -p "$WORKSPACE_DIR/.agents/skills"
```

## 3. 配置一个可暴露 Agent Pack

如果你已经按上面的方式复制了 `examples/demo-workspace`，这里可以跳过。

写入 `agent.yaml`：

```bash
cat > "$WORKSPACE_DIR/.agents/agents/demo-assistant/agent.yaml" <<'YAML'
exposed: true
tools:
  requested_tool_names:
    - core.web_fetch
skills:
  default_selected: []
multiagent:
  spawn_allow_agent_ids: ["demo-assistant"]
YAML
```

写入 `AGENTS.md`（业务定制提示）：

```bash
cat > "$WORKSPACE_DIR/.agents/agents/demo-assistant/AGENTS.md" <<'MD'
# Demo Assistant Policy
- 先给结论，再给步骤。
- 引用 URL 时给出来源可信度说明。
MD
```

## 4. 启动 Tool Runtime 与 Agent API

终端 A：

```bash
cd apps/tool-runtime
uv sync
uv run --env-file .env tool-runtime
```

终端 B：

```bash
cd apps/agent-api
uv sync
uv run --env-file .env agent-api
```

## 5. 发起一次带 agent_id/session_key 的请求

如果你是用 `.env` 启动服务（而不是 `export AGENT_API_KEY=...`），把下面的 `$AGENT_API_KEY` 替换为 `apps/agent-api/.env` 里的值即可（默认是 `dev-agent-api-key`）。

```bash
curl -sS "http://127.0.0.1:8787/v1/responses" \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4.1-mini",
    "input": "请先抓取 example.com 的标题，再给出一句总结",
    "metadata": {
      "agent_id": "demo-assistant",
      "session_key": "demo-thread-001"
    },
    "tools": [{"type":"function","name":"core.web_fetch"}],
    "tool_choice": {"type":"function","name":"core.web_fetch"}
  }'
```

验收点：

- 请求可被 `agent_id=demo-assistant` 正常路由
- 工具清单由 Tool Runtime manifest 收口，而非直接信任 caller `tools[]`
- 返回结果可看到 tool loop 完整闭环（先调用工具，再得到最终回答）

## 6. Skills 定制化（可选）

在 `"$WORKSPACE_DIR/.agents/skills/"` 新建一个 skill 包（最小结构：`SKILL.md` + frontmatter），然后通过：

- `metadata.skills` 显式指定
- 或在用户输入中 `$skill-id` mention

触发技能选择与注入。

可通过以下接口观察选择结果：

```bash
curl -sS "http://127.0.0.1:8787/internal/skills/list" \
  -H "Authorization: Bearer $AGENT_API_KEY"
```

## 7. 插件与凭证（可选）

插件加载：

- `TOOL_RUNTIME_PLUGIN_ROOTS` 支持逗号分隔多个根目录
- 每个根目录下“包含 `plugin.json` 的目录”即插件目录
- 插件可选 `config.json`，并按 `plugin.json.config_schema` 校验

凭证管理（Admin API）：

```bash
anyagent credential set \
  --admin-url http://127.0.0.1:8788 \
  --admin-key "$ADMIN_API_KEY" \
  --id feishu.default \
  --kind bearer_token \
  --value-from-env FEISHU_TOKEN \
  --scope global
```

## 8. 最小自动化验证

```bash
cd apps/agent-api
uv run -s ../../tests/acceptance/agent_api/acceptance_session_resume_smoke.py
uv run -s ../../tests/acceptance/storage/acceptance_rollout_storage_consistency_smoke.py --require-external
uv run --env-file .env --with openai -s ../../tests/acceptance/openai/acceptance_openai_sdk_smoke.py
```

## 9. 常见问题

- 401：检查 `Authorization: Bearer $AGENT_API_KEY`
- 502：检查 `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- tool 不可见：检查 Agent Pack `requested_tool_names`、skills 依赖、Tool Runtime policy
- `toolset_version_mismatch`：属于并发下的版本刷新保护，Agent API 会自动刷新 manifest 后重试一次
