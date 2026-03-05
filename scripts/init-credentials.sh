#!/usr/bin/env bash
# scripts/init-credentials.sh
#
# Batch import credentials into Tool Runtime CredentialStore via Admin API.
# This script is write-only by design: it never reads back plaintext values.

set -euo pipefail

CREDENTIALS_FILE="${1:-scripts/credentials.yaml.template}"
ADMIN_URL="${ADMIN_URL:-http://127.0.0.1:8788}"
ADMIN_API_KEY="${ADMIN_API_KEY:?ADMIN_API_KEY must be set}"

if command -v anyagent >/dev/null 2>&1; then
  anyagent credential import \
    --admin-url "${ADMIN_URL}" \
    --admin-key "${ADMIN_API_KEY}" \
    --file "${CREDENTIALS_FILE}" \
    --skip-missing
else
  python3 -m anyagent.cli credential import \
    --admin-url "${ADMIN_URL}" \
    --admin-key "${ADMIN_API_KEY}" \
    --file "${CREDENTIALS_FILE}" \
    --skip-missing
fi

