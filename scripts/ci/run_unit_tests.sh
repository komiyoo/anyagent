#!/usr/bin/env bash
set -euo pipefail

echo "[ci] pytest unit"

uv run --frozen --project packages/anyagent --extra external-storage python -m pytest tests/unit -q
