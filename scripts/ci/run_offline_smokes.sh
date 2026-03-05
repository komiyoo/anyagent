#!/usr/bin/env bash
set -euo pipefail

echo "[ci] offline smokes: protocol + storage + mcp + session runtime"

uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/mcp/acceptance_mcp_federation_smoke.py

uv run --frozen --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_replay_smoke.py
uv run --frozen --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_rotation_smoke.py
uv run --frozen --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_storage_consistency_smoke.py
uv run --frozen --project apps/agent-api python tests/acceptance/agent_api/acceptance_session_resume_smoke.py
uv run --frozen --project apps/agent-api python tests/acceptance/agent_api/acceptance_optional_responses_endpoints_smoke.py
