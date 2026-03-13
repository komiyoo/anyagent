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

## 推荐运行

```bash
# 离线 smoke（sdk + mcp）
bash scripts/ci/run_offline_smokes.sh

# built-in live matrix（PG primary + Redis hot / Redis lease）
ANYAGENT_TEST_POSTGRES_DSN=postgresql://... \
ANYAGENT_TEST_REDIS_DSN=redis://... \
uv run --project packages/anyagent --with pytest python -m pytest -q \
  tests/acceptance/server/acceptance_builtin_server_smoke.py \
  -k 'test_session_cached_store_pg_primary_redis_hot_roundtrip_live or test_session_redis_lease_active_during_inflight_request_live'

# built-in MySQL external smoke
ANYAGENT_TEST_MYSQL_DSN=mysql+asyncmy://... \
ANYAGENT_TEST_REDIS_DSN=redis://... \
uv run --project packages/anyagent python tests/acceptance/server/acceptance_mysql_builtin_server_smoke.py
```

应用层集成验收与在线兼容验收已迁到同级项目 `../anyagent-apps/tests/acceptance/`。
