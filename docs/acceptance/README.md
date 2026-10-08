# Acceptance 文档索引

当前仓库已收敛为配置化 built-in Agent Server + SDK：`anyagent serve` 从 workspace `.anyagent/` 配置启动 OpenAI Responses API 兼容服务，内置 in-process Tool Runtime 与最小存储。本仓只验收框架自身行为；业务 agent 的应用层验收由各业务仓库负责。

当前可执行的最小验收入口：

- CLI 配置生成与体检单测：`tests/unit/test_cli_workspace_commands.py`
- SDK/协议离线 smoke：`tests/acceptance/sdk/`
- MCP federation 离线 smoke：`tests/acceptance/mcp/`
- built-in server 主路径与存储/并发 smoke：`tests/acceptance/server/`

其中 Chatwoot connector 目前有两条专门验收入口：

- `tests/acceptance/server/acceptance_chatwoot_connector_smoke.py`
  说明：离线 in-process smoke，覆盖 `webhook -> /v1/responses -> gateway.handoff -> outbound/handoff`
- `tests/acceptance/server/acceptance_chatwoot_live_smoke.py`
  说明：真实 Chatwoot 环境 smoke，要求 `ANYAGENT_TEST_CHATWOOT_URL`、`ANYAGENT_TEST_CHATWOOT_ACCOUNT_ID`、`ANYAGENT_TEST_CHATWOOT_ACCESS_TOKEN`、`ANYAGENT_TEST_CHATWOOT_WEBHOOK_SECRET`、`ANYAGENT_TEST_CHATWOOT_CONVERSATION_ID`

Scripted reply（确定性回复扩展点）与 connector 回复节奏的验收入口：

- `tests/integration/server/test_scripted_reply_responses.py`
  说明：配置 workspace `src/` 内的 provider，两轮会话第一轮 scripted（0 模型调用、`anyagent.response.scripted` 事件、Chatwoot 提取器可读）、第二轮模型输入含第一轮合成回复；流式 SSE 为 delta → completed → [DONE]；装载失败 / 未命中降级走 loop
- `tests/unit/agent_runtime/test_scripted_reply.py`
  说明：契约、classpath 装载、先命中先返回、异常 / 超时 / 非法返回降级
- `tests/unit/gateway/test_chatwoot_reply_pacing.py` 与 `tests/integration/server/test_chatwoot_connector_flow.py::test_chatwoot_connector_applies_pacing_floor_and_typing_indicator`
  说明：节奏下限是 floor 不是 delay；typing on/off 成对；默认关闭零行为变化

```bash
uv run --project packages/anyagent pytest tests/unit/agent_runtime/test_scripted_reply.py tests/unit/gateway/test_chatwoot_reply_pacing.py tests/integration/server/test_scripted_reply_responses.py tests/integration/server/test_chatwoot_connector_flow.py -q
```
