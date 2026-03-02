# AnyAgent Agent API（Python）

本目录提供 `POST /v1/responses` 的 **OpenAI Responses API 兼容代理**（含 `stream=true` SSE 透传），用于快速跑通对外接口闭环。

## 启动

1) 准备环境变量（示例）：

- `AGENT_API_KEY=...`（对外鉴权）
- `OPENAI_API_KEY=...`（上游 OpenAI Key）
- `OPENAI_BASE_URL=https://api.openai.com/v1`（可选）
- `HOST=127.0.0.1`（可选）
- `PORT=8787`（可选）

2) 使用 uv 安装依赖并启动：

- `uv sync`
- `uv run anyagent-agent-api`

## API

- `GET /healthz`
- `GET /readyz`
- `POST /v1/responses`

