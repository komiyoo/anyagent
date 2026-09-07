#!/usr/bin/env bash
set -euo pipefail

# Drain hook stdin; sessionStart should not block the session if install fails.
cat >/dev/null || true

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

if [[ -x "$repo_root/scripts/install-git-hooks.sh" || -f "$repo_root/scripts/install-git-hooks.sh" ]]; then
  bash "$repo_root/scripts/install-git-hooks.sh" >/dev/null || true
fi

printf '%s\n' '{}'
