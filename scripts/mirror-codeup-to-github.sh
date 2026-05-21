#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "$*" >&2
  exit 1
}

repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd
}

# Avoid leaking token-bearing remote URLs if the surrounding CI step enables xtrace.
case "$-" in
  *x*) set +x ;;
esac

cd "$(repo_root)"

remote_name="github-mirror-$$"
mirror_repo="${GITHUB_MIRROR_REPO:-${ANYAGENT_GITHUB_MIRROR_REPO:-}}"
mirror_remote_url="${GITHUB_MIRROR_REMOTE_URL:-${ANYAGENT_GITHUB_REMOTE_URL:-}}"
mirror_url_prefix="${GITHUB_MIRROR_URL_PREFIX:-}"
mirror_token="${GITHUB_TOKEN:-}"
mirror_branches="${GITHUB_MIRROR_BRANCHES:-${CI_COMMIT_REF_NAME:-main}}"
mirror_push_tags="${GITHUB_MIRROR_PUSH_TAGS:-false}"
mirror_dry_run="${GITHUB_MIRROR_DRY_RUN:-false}"
mirror_required="${GITHUB_MIRROR_REQUIRED:-0}"
mirror_push_retries="${GITHUB_MIRROR_PUSH_RETRIES:-3}"
mirror_push_retry_sleep="${GITHUB_MIRROR_PUSH_RETRY_SLEEP_SECONDS:-8}"
mirror_push_timeout="${GITHUB_MIRROR_PUSH_TIMEOUT_SECONDS:-120}"
mirror_auth_header=""

cleanup() {
  git remote remove "${remote_name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

skip_or_fail() {
  if [[ "${mirror_required}" == "1" ]]; then
    fail "$*"
  fi
  echo "$*; skip GitHub mirror."
  exit 0
}

if [[ "${mirror_remote_url}" == "REPLACE_ME" ]]; then
  mirror_remote_url=""
fi
if [[ "${mirror_repo}" == "REPLACE_ME" ]]; then
  mirror_repo=""
fi

if [[ -z "${mirror_remote_url}" ]]; then
  if [[ -z "${mirror_repo}" ]]; then
    skip_or_fail "GITHUB_MIRROR_REPO is not configured"
  fi

  if [[ "${mirror_repo}" == http://* || "${mirror_repo}" == https://* || "${mirror_repo}" != */* ]]; then
    fail "GITHUB_MIRROR_REPO must be an owner/repo slug. Use GITHUB_MIRROR_REMOTE_URL for a full remote URL."
  fi

  if [[ -z "${mirror_token}" || "${mirror_token}" == "REPLACE_ME" ]]; then
    skip_or_fail "GITHUB_TOKEN is not configured"
  fi

  if [[ -n "${mirror_url_prefix}" ]]; then
    if [[ "${mirror_url_prefix}" != http://* && "${mirror_url_prefix}" != https://* ]]; then
      fail "GITHUB_MIRROR_URL_PREFIX must start with http:// or https://."
    fi

    mirror_remote_url="${mirror_url_prefix%/}/https://github.com/${mirror_repo}.git"
    mirror_auth_header="$(printf 'x-access-token:%s' "${mirror_token}" | base64 | tr -d '\n')"
  else
    mirror_remote_url="https://x-access-token:${mirror_token}@github.com/${mirror_repo}.git"
  fi
fi

branches=()
source_prefix="refs/heads"

if [[ "${mirror_branches}" == "all" ]]; then
  git remote get-url origin >/dev/null 2>&1 || fail "An origin remote is required when GITHUB_MIRROR_BRANCHES=all."

  echo "Fetching all branches from Codeup origin..."
  git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
  source_prefix="refs/remotes/origin"

  while IFS= read -r ref; do
    branch="${ref#refs/remotes/origin/}"
    if [[ -n "${branch}" && "${branch}" != "HEAD" ]]; then
      branches+=("${branch}")
    fi
  done < <(git for-each-ref --format='%(refname)' refs/remotes/origin)
else
  read -r -a branches <<<"${mirror_branches}"
fi

if [[ "${#branches[@]}" -eq 0 ]]; then
  fail "No branches found to mirror. Check GITHUB_MIRROR_BRANCHES and the origin remote."
fi

[[ "${mirror_push_retries}" =~ ^[1-9][0-9]*$ ]] || fail "GITHUB_MIRROR_PUSH_RETRIES must be a positive integer."
[[ "${mirror_push_retry_sleep}" =~ ^[0-9]+$ ]] || fail "GITHUB_MIRROR_PUSH_RETRY_SLEEP_SECONDS must be a non-negative integer."
[[ "${mirror_push_timeout}" =~ ^[1-9][0-9]*$ ]] || fail "GITHUB_MIRROR_PUSH_TIMEOUT_SECONDS must be a positive integer."

git remote add "${remote_name}" "${mirror_remote_url}"

push_args=()
if [[ "${mirror_dry_run}" == "true" ]]; then
  push_args+=(--dry-run)
  echo "Dry run enabled; no refs will be updated."
fi

mirror_git_push_with_retry() {
  local attempt=1
  local git_command=(git)
  local git_push_args=(push)

  if [[ -n "${mirror_auth_header}" ]]; then
    git_command+=(-c "http.extraHeader=Authorization: Basic ${mirror_auth_header}")
  fi

  if [[ "${#push_args[@]}" -gt 0 ]]; then
    git_push_args+=("${push_args[@]}")
  fi

  while true; do
    if command -v timeout >/dev/null 2>&1; then
      GIT_TERMINAL_PROMPT=0 timeout "${mirror_push_timeout}" "${git_command[@]}" "${git_push_args[@]}" "$@" && return 0
    else
      GIT_TERMINAL_PROMPT=0 "${git_command[@]}" "${git_push_args[@]}" "$@" && return 0
    fi

    if (( attempt >= mirror_push_retries )); then
      return 1
    fi

    echo "GitHub push failed; retrying in ${mirror_push_retry_sleep}s (${attempt}/${mirror_push_retries})..."
    sleep "${mirror_push_retry_sleep}"
    attempt=$((attempt + 1))
  done
}

for branch in "${branches[@]}"; do
  if [[ -z "${branch}" ]]; then
    continue
  fi

  source_ref="${source_prefix}/${branch}"
  if ! git show-ref --verify --quiet "${source_ref}"; then
    if git show-ref --verify --quiet "refs/heads/${branch}"; then
      source_ref="refs/heads/${branch}"
    else
      fail "Branch '${branch}' does not exist locally or under origin. Fetch or check out the branch before mirroring."
    fi
  fi

  echo "Mirroring branch ${branch} to GitHub..."
  mirror_git_push_with_retry "${remote_name}" "${source_ref}:refs/heads/${branch}"
done

case "${mirror_push_tags}" in
  true)
    echo "Mirroring tags to GitHub..."
    mirror_git_push_with_retry "${remote_name}" --tags
    ;;
  false)
    ;;
  *)
    fail "GITHUB_MIRROR_PUSH_TAGS must be 'true' or 'false'."
    ;;
esac

echo "GitHub mirror completed."
