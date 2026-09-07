#!/usr/bin/env bash
set -euo pipefail

echo "[ci] pre-commit gate: docs + unit"

bash scripts/ci/run_docs_guardrails.sh
bash scripts/ci/run_unit_tests.sh
