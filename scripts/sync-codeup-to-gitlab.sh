#!/usr/bin/env bash
set -euo pipefail

remote_name="${GITLAB_REMOTE_NAME:-gitlab}"
branch="${SYNC_BRANCH:-${CI_COMMIT_REF_NAME:-${BUILD_SOURCEBRANCHNAME:-main}}}"
remote_url="${ANYAGENT_GITLAB_REMOTE_URL:-${GITLAB_REMOTE_URL:-}}"
required="${GITLAB_SYNC_REQUIRED:-0}"
username="${GITLAB_USERNAME:-oauth2}"
token="${GITLAB_TOKEN:-}"
proxy_url="${GIT_STANDARD_PROXY_URL:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}"

if [[ -z "$remote_url" ]]; then
  if [[ "$required" == "1" ]]; then
    echo "ANYAGENT_GITLAB_REMOTE_URL or GITLAB_REMOTE_URL is required for GitLab sync."
    exit 1
  fi
  echo "GitLab remote URL is not configured; skip GitLab sync."
  exit 0
fi

auth_url="$remote_url"
if [[ "$remote_url" != *"@"* ]]; then
  if [[ -z "$token" ]]; then
    if [[ "$required" == "1" ]]; then
      echo "GITLAB_TOKEN is required for HTTPS GitLab sync."
      exit 1
    fi
    echo "GITLAB_TOKEN is not configured; skip GitLab sync."
    exit 0
  fi

  auth_url="$(
    python - "$remote_url" "$username" "$token" <<'PY'
import sys
from urllib.parse import quote, urlsplit, urlunsplit

raw_url, username, token = sys.argv[1:4]
parts = urlsplit(raw_url)
netloc = f"{quote(username, safe='')}:{quote(token, safe='')}@{parts.hostname}"
if parts.port:
    netloc += f":{parts.port}"
print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
  )"
fi

git remote remove "$remote_name" >/dev/null 2>&1 || true
git remote add "$remote_name" "$auth_url"

echo "Syncing current Codeup commit to GitLab branch ${branch}."
if [[ -n "$proxy_url" ]]; then
  git -c http.proxy="$proxy_url" -c https.proxy="$proxy_url" push "$remote_name" "HEAD:${branch}"
else
  git push "$remote_name" "HEAD:${branch}"
fi

if [[ "${SYNC_TAGS:-0}" == "1" ]]; then
  echo "Syncing tags to GitLab."
  if [[ -n "$proxy_url" ]]; then
    git -c http.proxy="$proxy_url" -c https.proxy="$proxy_url" push "$remote_name" --tags
  else
    git push "$remote_name" --tags
  fi
fi
