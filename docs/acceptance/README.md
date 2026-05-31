# Acceptance 文档索引

当前仓库已收敛为配置化 built-in Agent Server + SDK：`anyagent serve` 从 workspace `.anyagent/` 配置启动 OpenAI Responses API 兼容服务，内置 in-process Tool Runtime 与最小存储；生产级分布式实践模板仍在同级项目 `../anyagent-apps/`。

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

如需运行应用层集成验收、Responses API 在线兼容验收或 demo 定制化回归，请到同级项目 `../anyagent-apps/docs/acceptance/`。
