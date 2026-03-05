# anyagent Agent API（Python）

本目录提供 `POST /v1/responses` 的 **OpenAI Responses API 兼容代理**（含 `stream=true` SSE 透传），用于快速跑通对外接口闭环。

## 启动

1. 准备环境变量（示例）：

- `AGENT_API_KEY=...`（对外鉴权）
- `OPENAI_API_KEY=...`（上游 OpenAI Key）
- `OPENAI_BASE_URL=https://api.openai.com/v1`（可选）
- `TOOL_RUNTIME_INTERNAL_KEY=...`（Agent API -> Tool Runtime 内部鉴权）
- `TOOL_RUNTIME_BASE_URL=http://127.0.0.1:8788`（可选）
- `POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:35432/anyagent`（可选：外部存储；默认不配则走 in-memory/rollout）
- `REDIS_DSN=redis://127.0.0.1:35433/0`（可选：外部存储；Lease Lock 等能力）
- `WORKSPACE_DIR=/path/to/your/workspace`（必需：用于加载 `.agents/agents/<agent_id>/` 与 `.agents/skills/`）
- `ROLLOUT_ROOT_DIR=/path/to/.runs/rollouts`（可选：`STORAGE_MODE=none` 时本地 rollout 持久化根目录）
- `ROLLOUT_ROTATE_MAX_BYTES=10485760`（可选：单文件达到阈值后轮转；默认 0=关闭）
- `ROLLOUT_ROTATE_MAX_AGE_SECONDS=86400`（可选：文件年龄达到阈值后轮转；默认 0=关闭）
- `ROLLOUT_ROTATE_KEEP_FILES=16`（可选：每个 session 保留的归档 rollout 文件数）
- `HOST=127.0.0.1`（可选）
- `PORT=8787`（可选）

2. 使用 uv 安装依赖并启动：

- `uv sync`
- `uv run agent-api`

（可选）本仓库提供本地存储开发环境 compose：

- `docker compose -f docker-compose.storage.yml up -d`

## 运维

- 迁移：`POSTGRES_DSN=... uv run agent-api-migrate`
- 清理（默认 plan-only）：`POSTGRES_DSN=... uv run agent-api-retention`
- 清理（实际执行）：`POSTGRES_DSN=... uv run agent-api-retention --apply`
- rollout 回放：`uv run agent-api-rollout-replay --session-partition-key '<agent_id>::<session_key>' --last-seq 0`
- session 恢复/参数绑定 smoke：`uv run --project apps/agent-api python scripts/acceptance_session_resume_smoke.py`
- rollout 存储一致性 smoke（none vs external）：`uv run --project apps/agent-api python scripts/acceptance_rollout_storage_consistency_smoke.py --require-external`
- rollout 轮转 smoke：`uv run --project apps/agent-api python scripts/acceptance_rollout_rotation_smoke.py`

## API

- `GET /healthz`
- `GET /readyz`
- `POST /v1/responses`
- `GET /internal/skills/list`（鉴权同 `/v1/responses`）
- `GET /internal/events/list?response_id=...&last_seq=...`（按游标补发事件）
- `GET /internal/events/stream?response_id=...&last_seq=...`（SSE：先补发再追尾）
  - 约定：SSE `id:` 字段即 Event Store 的 `seq`（单调递增游标）；SDK 会将其映射到 `StageEvent.seq`

## Demo 定制化入口

`apps/agent-api` 在本仓库中定位为“应用级编排 demo”：

- 读取 `WORKSPACE_DIR/.agents/agents/<agent_id>/agent.yaml + AGENTS.md`
- 根据 `metadata.agent_id` / `metadata.session_key` 做会话分片和策略收口
- 动态拼接 skills + Tool Runtime manifest，形成最终可见工具集合

快速验证（示例）：

```bash
curl -sS "http://127.0.0.1:8787/v1/responses" \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"gpt-4.1-mini",
    "input":"总结 example.com 首页标题",
    "metadata":{"agent_id":"main","session_key":"demo-001"},
    "tools":[{"type":"function","name":"core.web_fetch"}],
    "tool_choice":{"type":"function","name":"core.web_fetch"}
  }'
```

完整实操（含 Agent Packs/skills/插件/凭证）见：

- `docs/acceptance/acceptance-demo-customization.md`
- `docs/acceptance/acceptance-responses-api.md`

## v0 约束（重要）

Agent API 以配置目录（Agent Packs）作为多 agent 的单一真源：

- `<workspace>/.agents/agents/<agent_id>/agent.yaml`
- `<workspace>/.agents/agents/<agent_id>/AGENTS.md`

Agent API **不信任**外部请求传入的 `tools` / `tool_choice`：

- 外部 `tools[]` 仅作为 `requested_tool_names/requested_tools` 传给 Tool Runtime `manifest` 用于“期望集合/审计”
- 最终传给模型的 `tools[]` 必须以 Tool Runtime `manifest.tools[]` 为准
- `stream=true` 支持 server-side tool loop，但当前实现为“先缓冲上游 SSE，再一次性回放给客户端”（保证 `[DONE]` 仅出现一次）
- 当未配置外部存储（`STORAGE_MODE=none`）时，会在本地按 `session_partition_key` 追加写入 `rollout.jsonl`（append-only，写入路径判重）
- 同一 `session_partition_key` 会加载/回写 Session Store 快照（`runtime_config + resume_cursor + snapshot_version`），用于 Session Resume 与会话级运行参数绑定
