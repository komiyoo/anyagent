#!/usr/bin/env bash
set -euo pipefail

echo "[ci] docs guardrails"
python3 scripts/docs/check.py --root .
python3 scripts/anyagent_progress.py --root .

