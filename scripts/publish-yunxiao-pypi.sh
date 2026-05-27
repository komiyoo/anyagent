#!/usr/bin/env bash
set -euo pipefail

export PIP_DISABLE_PIP_VERSION_CHECK="${PIP_DISABLE_PIP_VERSION_CHECK:-1}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.aliyun.com}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.cache/pip}"
mkdir -p "$PIP_CACHE_DIR"

export TWINE_REPOSITORY_URL="${TWINE_REPOSITORY_URL:-${ANYAGENT_PYPI_REPOSITORY_URL:-https://packages.aliyun.com/63d476f8d14a7f379aa798da/pypi/anyagent}}"
export TWINE_USERNAME="${TWINE_USERNAME:-${ANYAGENT_PYPI_USERNAME:-63c537efbb097da55ff323e3}}"

if [[ -z "${TWINE_PASSWORD:-}" || "${TWINE_PASSWORD:-}" == "REPLACE_ME" ]]; then
  echo "TWINE_PASSWORD encrypted variable is not configured; skip package publish."
  exit 0
fi

if ! python -m twine --version >/dev/null 2>&1; then
  python -m pip install twine
fi

package_dir="packages/anyagent"
package_name="$(
  python - "$package_dir/pyproject.toml" <<'PY'
from pathlib import Path
import sys
import tomllib

payload = tomllib.loads(Path(sys.argv[1]).read_text())
print(payload["project"]["name"])
PY
)"
package_version="$(
  python - "$package_dir/pyproject.toml" <<'PY'
from pathlib import Path
import sys
import tomllib

payload = tomllib.loads(Path(sys.argv[1]).read_text())
print(payload["project"]["version"])
PY
)"

auth_index_url="$(
  python - "$TWINE_REPOSITORY_URL" "$TWINE_USERNAME" "$TWINE_PASSWORD" <<'PY'
import sys
from urllib.parse import quote, urlsplit, urlunsplit

raw_url, username, password = sys.argv[1:4]
parts = urlsplit(raw_url)
netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.hostname}"
if parts.port:
    netloc += f":{parts.port}"
print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
)"

check_dir="$(mktemp -d)"
trap 'rm -rf "$check_dir"' EXIT

if python -m pip download \
  --quiet \
  --no-deps \
  --dest "$check_dir" \
  --trusted-host packages.aliyun.com \
  --index-url "$auth_index_url" \
  --extra-index-url https://mirrors.aliyun.com/pypi/simple \
  "${package_name}==${package_version}" >/dev/null 2>&1; then
  echo "${package_name}==${package_version} already exists in Yunxiao Packages; skip package publish."
  exit 0
fi

echo "${package_name}==${package_version} is not present in Yunxiao Packages yet; publishing ${package_dir}/dist/*."
python -m twine check "${package_dir}"/dist/*
python -m twine upload "${package_dir}"/dist/*
