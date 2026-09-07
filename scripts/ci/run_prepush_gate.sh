#!/usr/bin/env bash
set -euo pipefail

echo "[ci] pre-push gate: pytest regressions + offline smokes"

bash scripts/ci/run_pytest_regressions.sh
bash scripts/ci/run_offline_smokes.sh
