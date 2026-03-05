# Responses API 兼容性验收清单（v0）

对应需求：`requirements.md#req-9-1`

本清单目标：用 **OpenAI 官方 SDK** 将 `base_url` 指向 anyagent Agent API，验证以下能力可跑通：

- 非流式 `POST /v1/responses`
- 流式 `stream=true` SSE：事件顺序可消费、能读到最终 `response.completed`、以 `[DONE]` 结束
- 至少一次 function tool call：Tool Runtime execute 后继续推理并产出最终回答

如果你需要“应用级定制化（Agent Packs/skills/插件/凭证）”的一站式实操，请优先参考：

- `docs/acceptance/acceptance-demo-customization.md`

## 0. 前置条件

1. 启动 Tool Runtime（默认端口 `8788`）与 Agent API（默认端口 `8787`）
2. 配置鉴权：
   - Agent API：`AGENT_API_KEY`
   - Tool Runtime：`TOOL_RUNTIME_INTERNAL_KEY`

注意：

- SDK 侧的 `api_key` 对 anyagent 不重要，但 **必须**提供一个非空值以满足 SDK 校验。
- Agent API 的鉴权在 HTTP header：`Authorization: Bearer <AGENT_API_KEY>`。

## 1. 非流式（必测）

验收点：

- HTTP 200
- 返回 JSON object，包含 `id`
- 最终回答可从 `output[]` 中提取（格式允许随 OpenAI Responses 演进；这里以“能正常被 SDK 解析”为准）

### Python（OpenAI SDK）

推荐直接跑仓库内 smoke（优先复用官方 SDK 的 request/stream schema）：

```bash
export ANYAGENT_AGENT_API_BASE_URL="http://127.0.0.1:8787"
export AGENT_API_KEY="..."
export ANYAGENT_OPENAI_MODEL="gpt-4.1-mini"

cd apps/agent-api
uv run --with openai -s ../../scripts/acceptance_openai_sdk_smoke.py
```

说明：

- 这里用 `uv run --with openai` 临时安装官方 SDK（不修改 lock）。
- SDK 的 `api_key` 对 anyagent 会被当作 `Authorization: Bearer ...` 使用，因此建议直接使用 `AGENT_API_KEY`。

伪代码（以官方 SDK 的 `base_url` 方式为准）：

- `base_url = "http://127.0.0.1:8787/v1"`
- `model` 可用任意上游支持的模型名（由 anyagent 透传到上游）
- 请求 body 至少包含 `input`

## 2. 流式 SSE（必测）

验收点：

- SDK 能持续读取事件
- 事件流最终包含 `response.completed`
- 最后一帧为 `[DONE]`
- 慢消费者（客户端慢读）时，服务端不应无限缓冲导致 RSS 线性增长（可用简单观察验证）

## 3. 工具调用闭环（必测）

目标：强制模型产生一次 `function_call`，由 Tool Runtime 执行后继续推理得到最终回答。

推荐策略：

- 在请求里显式请求 `core.web_fetch` 工具可见（通过 `tools[]` 或 AgentSpec/skills 依赖触发 manifest）
- 用 `tool_choice` 强制调用该工具（避免模型“不想用工具”导致验收不稳定）

注意：

- `core.web_fetch` 存在 SSRF 防护：禁止 `localhost/127.0.0.1/169.254.*` 等地址；验收 URL 推荐使用 `https://example.com/`。

补充：

- `tools[]` / `tool_choice` 建议使用 OpenAI Responses SDK 形态（`{"type":"function","name":"..."}`），anyagent 会用 Tool Runtime manifest 的完整 schema 覆盖上游 `tools[]`。

验收点：

- `stream=false`：最终 response 能完成，并包含 tool 调用后的最终回答
- `stream=true`：事件中出现 function_call 相关事件；最终仍能完成并 `[DONE]`

## 4. 常见失败与排查

- 401：检查 Agent API 的 `Authorization: Bearer ...`
- 502/Upstream error：检查 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`
- tool 不可见：
  - 检查 Tool Runtime 是否启动
  - 检查 Tool Runtime policy 是否允许（默认允许 `core.*`，但仍可能被 deny）
  - 检查 `requested_tool_names` 是否包含目标工具名

## 5. MCP 并行工具源验收（v0）

目标：验证 MCP 作为 Agent API 并行工具来源可被正确加载、合并与路由（不依赖真实外部 MCP server）。

推荐运行：

```bash
cd apps/agent-api
uv run -s ../../scripts/acceptance_mcp_federation_smoke.py
```

验收点：

- Agent Pack 的 `mcp.json` 可被加载并做 transport 推断
- skill dependency `transport: mcp` 映射到 `mcp.<label>.*`
- MCP manager 可把工具转换为 `mcp.<label>.<tool>` 并完成调用路由
- SDK helper `resolve_manifest_with_mcp` 可合并 Tool Runtime 与 MCP 工具清单
