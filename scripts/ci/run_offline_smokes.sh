#!/usr/bin/env bash
set -euo pipefail

echo "[ci] offline smokes: sdk + mcp"

uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_stage_event_trace_id_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_events_replay_done_persisted_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_tool_credential_injection_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_exec_output_truncation_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_credential_audit_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/mcp/acceptance_mcp_federation_smoke.py
