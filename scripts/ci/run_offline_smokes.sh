#!/usr/bin/env bash
set -euo pipefail

echo "[ci] offline smokes: sdk + mcp"

uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py
uv run --frozen --project packages/anyagent python tests/acceptance/mcp/acceptance_mcp_federation_smoke.py
