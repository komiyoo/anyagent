#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ ! -d .githooks ]]; then
  echo "install-git-hooks: missing .githooks/" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "install-git-hooks: not a git work tree" >&2
  exit 1
fi

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/pre-push scripts/ci/run_unit_tests.sh \
  scripts/ci/run_precommit_gate.sh scripts/ci/run_prepush_gate.sh

echo "Installed git hooksPath=.githooks"
echo "  commit -> scripts/ci/run_precommit_gate.sh (docs + unit)"
echo "  push   -> scripts/ci/run_prepush_gate.sh (pytest regressions + offline smokes)"
