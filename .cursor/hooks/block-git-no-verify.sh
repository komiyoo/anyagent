#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
export ANYAGENT_HOOK_PAYLOAD="$payload"

python3 - <<'PY'
import json
import os
import re
import sys

raw = os.environ.get("ANYAGENT_HOOK_PAYLOAD") or ""
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}

command = str(payload.get("command") or "")
normalized = " ".join(command.split())
is_git_commit = re.search(r"(^|[;&|]\s*)git(\s+-C\s+\S+)?\s+commit\b", normalized) is not None
is_git_push = re.search(r"(^|[;&|]\s*)git(\s+-C\s+\S+)?\s+push\b", normalized) is not None
skips_hooks = bool(re.search(r"(^|\s)--no-verify(\s|$)", normalized))
skips_commit_hooks = is_git_commit and bool(re.search(r"(^|\s)-n(\s|$)", normalized))

if (is_git_commit or is_git_push) and (skips_hooks or skips_commit_hooks):
    message = (
        "anyagent local quality gates must run on commit/push. "
        "Do not use --no-verify unless the user explicitly asked to skip. "
        "Install hooks with: bash scripts/install-git-hooks.sh"
    )
    json.dump(
        {
            "permission": "deny",
            "user_message": message,
            "agent_message": message,
        },
        sys.stdout,
    )
    sys.exit(0)

json.dump({"permission": "allow"}, sys.stdout)
PY
