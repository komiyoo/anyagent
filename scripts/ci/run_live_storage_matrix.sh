#!/usr/bin/env bash
set -euo pipefail

echo "[ci] live storage matrix: postgres/redis + mysql/redis"

: "${ANYAGENT_TEST_POSTGRES_DSN:?ANYAGENT_TEST_POSTGRES_DSN is required}"
: "${ANYAGENT_TEST_REDIS_DSN:?ANYAGENT_TEST_REDIS_DSN is required}"
: "${ANYAGENT_TEST_MYSQL_DSN:?ANYAGENT_TEST_MYSQL_DSN is required}"

uv run --project packages/anyagent --with pytest python -m pytest -q \
  tests/acceptance/server/acceptance_builtin_server_smoke.py \
  -k 'test_session_cached_store_pg_primary_redis_hot_roundtrip_live or test_session_redis_lease_active_during_inflight_request_live'

ANYAGENT_TEST_MYSQL_DSN="${ANYAGENT_TEST_MYSQL_DSN}" \
ANYAGENT_TEST_REDIS_DSN="${ANYAGENT_TEST_REDIS_DSN}" \
uv run --project packages/anyagent python tests/acceptance/server/acceptance_mysql_builtin_server_smoke.py
