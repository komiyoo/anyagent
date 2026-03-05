# tests/acceptance（验收脚本）

本目录按模块分层沉淀 acceptance/smoke 脚本，覆盖：

- 对外 Responses API 兼容面（离线/在线两类）
- 存储与 replay/session resume 等可重放关键链路
- MCP federation（离线 fake server）
- SDK 强类型事件解析等协议一致性

## 目录

- [agent_api/README.md](agent_api/README.md)
- [storage/README.md](storage/README.md)
- [mcp/README.md](mcp/README.md)
- [sdk/README.md](sdk/README.md)
- [openai/README.md](openai/README.md)

## 推荐运行

```bash
# 离线 smoke（协议 + 存储 + mcp + session runtime）
bash scripts/ci/run_offline_smokes.sh
```

在线验收（需要 API Key/OpenAI SDK）请按 `docs/acceptance/acceptance-responses-api.md` 的步骤执行。

