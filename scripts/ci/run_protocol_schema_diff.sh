#!/usr/bin/env bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
BASE_REMOTE_REF="origin/${BASE_REF}"
BASE_SCHEMA="$(mktemp)"
HEAD_SCHEMA="$(mktemp)"

cleanup() {
  rm -f "${BASE_SCHEMA}" "${HEAD_SCHEMA}"
}
trap cleanup EXIT

if ! git rev-parse --verify --quiet "${BASE_REMOTE_REF}" >/dev/null; then
  echo "protocol schema diff: base ref ${BASE_REMOTE_REF} unavailable, skipping"
  exit 0
fi

if ! git show "${BASE_REMOTE_REF}:sdks/typescript/generated/protocol-schema.json" >"${BASE_SCHEMA}"; then
  echo "protocol schema diff: base schema unavailable on ${BASE_REMOTE_REF}, skipping"
  exit 0
fi

uv run --project packages/anyagent python scripts/export_protocol_schema.py --out "${HEAD_SCHEMA}"
uv run --project packages/anyagent python scripts/protocol_schema_diff.py --old "${BASE_SCHEMA}" --new "${HEAD_SCHEMA}"
