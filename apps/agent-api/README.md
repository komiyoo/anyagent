# AnyAgent Agent API（Python）

本目录提供 `POST /v1/responses` 的 **OpenAI Responses API 兼容代理**（含 `stream=true` SSE 透传），用于快速跑通对外接口闭环。

## 启动

1) 准备环境变量（示例）：

- `AGENT_API_KEY=...`（对外鉴权）
- `OPENAI_API_KEY=...`（上游 OpenAI Key）
- `OPENAI_BASE_URL=https://api.openai.com/v1`（可选）
- `TOOL_RUNTIME_INTERNAL_KEY=...`（Agent API -> Tool Runtime 内部鉴权）
- `TOOL_RUNTIME_BASE_URL=http://127.0.0.1:8788`（可选）
- `WORKSPACE_DIR=/path/to/your/workspace`（必需：用于加载 `.agents/agents/<agent_id>/` 与 `.agents/skills/`）
- `HOST=127.0.0.1`（可选）
- `PORT=8787`（可选）

2) 使用 uv 安装依赖并启动：

- `uv sync`
- `uv run agent-api`

## 运维

- 迁移：`POSTGRES_DSN=... uv run agent-api-migrate`
- 清理（默认 plan-only）：`POSTGRES_DSN=... uv run agent-api-retention`
- 清理（实际执行）：`POSTGRES_DSN=... uv run agent-api-retention --apply`

## API

- `GET /healthz`
- `GET /readyz`
- `POST /v1/responses`
- `GET /internal/skills/list`（鉴权同 `/v1/responses`）
- `GET /internal/events/list?response_id=...&last_seq=...`（按游标补发事件）
- `GET /internal/events/stream?response_id=...&last_seq=...`（SSE：先补发再追尾）

## v0 约束（重要）

Agent API 以配置目录（Agent Packs）作为多 agent 的单一真源：

- `<workspace>/.agents/agents/<agent_id>/agent.yaml`
- `<workspace>/.agents/agents/<agent_id>/AGENTS.md`

Agent API **不信任**外部请求传入的 `tools` / `tool_choice`：

- 外部 `tools[]` 仅作为 `requested_tool_names/requested_tools` 传给 Tool Runtime `manifest` 用于“期望集合/审计”
- 最终传给模型的 `tools[]` 必须以 Tool Runtime `manifest.tools[]` 为准
- `stream=true` 支持 server-side tool loop，但当前实现为“先缓冲上游 SSE，再一次性回放给客户端”（保证 `[DONE]` 仅出现一次）
