# tests/acceptance（验收脚本）

本目录当前仅保留面向 `packages/anyagent` 的 acceptance/smoke 脚本，覆盖：

- MCP federation（离线 fake server）
- SDK 强类型事件解析、Client surface、事件回放与安全主路径
- 内置 server 主路径与存储/并发相关验收
- 内置 server 的 PG/Redis live 路径与 MySQL external storage smoke

## 目录

- [mcp/README.md](mcp/README.md)
- [sdk/README.md](sdk/README.md)
- `server/acceptance_builtin_server_smoke.py`（PG/Redis live 用例需 `ANYAGENT_TEST_POSTGRES_DSN` 与 `ANYAGENT_TEST_REDIS_DSN`）
- `server/acceptance_mysql_builtin_server_smoke.py`（需 `ANYAGENT_TEST_MYSQL_DSN` 与 `ANYAGENT_TEST_REDIS_DSN`）
- `server/acceptance_chatwoot_connector_smoke.py`（离线 Chatwoot connector 主链路 smoke）
- `server/acceptance_chatwoot_live_smoke.py`（真实 Chatwoot 环境 smoke，需 `ANYAGENT_TEST_CHATWOOT_*` 变量）

## 推荐运行

```bash
# 离线 smoke（sdk + mcp）
bash scripts/ci/run_offline_smokes.sh

# formal pytest regressions
bash scripts/ci/run_pytest_regressions.sh

# built-in live matrix（PG primary + Redis hot / Redis lease）
ANYAGENT_TEST_POSTGRES_DSN=postgresql://... \
ANYAGENT_TEST_REDIS_DSN=redis://... \
bash scripts/ci/run_live_storage_matrix.sh

# built-in MySQL external smoke
ANYAGENT_TEST_MYSQL_DSN=mysql+asyncmy://... \
ANYAGENT_TEST_REDIS_DSN=redis://... \
uv run --project packages/anyagent python tests/acceptance/server/acceptance_mysql_builtin_server_smoke.py

# Chatwoot connector live smoke
ANYAGENT_TEST_CHATWOOT_URL=https://chatwoot.example \
ANYAGENT_TEST_CHATWOOT_ACCOUNT_ID=1 \
ANYAGENT_TEST_CHATWOOT_ACCESS_TOKEN=... \
ANYAGENT_TEST_CHATWOOT_WEBHOOK_SECRET=... \
ANYAGENT_TEST_CHATWOOT_CONVERSATION_ID=42 \
uv run --project packages/anyagent pytest tests/acceptance/server/acceptance_chatwoot_live_smoke.py -q
```

应用层集成验收与在线兼容验收已迁到同级项目 `../anyagent-apps/tests/acceptance/`。
