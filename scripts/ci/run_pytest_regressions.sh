#!/usr/bin/env bash
set -euo pipefail

echo "[ci] pytest regressions: unit + contract + integration + targeted server acceptance"

uv run --project packages/anyagent --extra external-storage --with pytest python -m pytest tests/unit -q
uv run --project packages/anyagent --extra external-storage --with pytest python -m pytest tests/contract -q
uv run --project packages/anyagent --extra external-storage --with pytest python -m pytest tests/integration -q
uv run --project packages/anyagent --extra external-storage --with pytest python -m pytest -q \
  tests/acceptance/server/acceptance_skills_list_smoke.py \
  tests/acceptance/server/acceptance_prompt_envelope_smoke.py \
  tests/acceptance/server/acceptance_builtin_server_smoke.py \
  -k 'test_builtin_server_exec_and_events_smoke or test_internal_events_stream_replays_and_tails or test_session_previous_response_id_injected_from_snapshot or test_session_store_rejects_stale_snapshot_version or test_session_fallback_transcript_items_used_when_last_response_id_missing'
