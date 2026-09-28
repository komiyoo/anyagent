#!/usr/bin/env bash
set -euo pipefail

package_dir="${ANYAGENT_TYPESCRIPT_SDK_DIR:-sdks/typescript}"
registry_url="${ANYAGENT_NPM_REGISTRY_URL:-https://packages.aliyun.com/63d476f8d14a7f379aa798da/npm/npm-registry/}"
token="${ANYAGENT_NPM_TOKEN:-${NPM_TOKEN:-}}"
username="${ANYAGENT_NPM_USERNAME:-63c537efbb097da55ff323e3}"
password="${NPM_PASSWORD:-${ANYAGENT_NPM_PASSWORD:-}}"
email="${ANYAGENT_NPM_EMAIL:-anyagent@example.com}"

if [[ ( -z "$token" || "$token" == "REPLACE_ME" ) && ( -z "$password" || "$password" == "REPLACE_ME" ) ]]; then
  if [[ "${ANYAGENT_PUBLISH_REQUIRED:-0}" == "1" ]]; then
    echo "ANYAGENT_NPM_TOKEN/NPM_TOKEN or NPM_PASSWORD/ANYAGENT_NPM_PASSWORD is not configured; refusing to skip npm package publish." >&2
    exit 1
  fi
  echo "ANYAGENT_NPM_TOKEN/NPM_TOKEN or NPM_PASSWORD/ANYAGENT_NPM_PASSWORD encrypted variable is not configured; skip npm package publish."
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to publish ${package_dir}." >&2
  exit 1
fi

package_name="$(
  node -e "const p=require('./${package_dir}/package.json'); console.log(p.name)"
)"
package_version="$(
  node -e "const p=require('./${package_dir}/package.json'); console.log(p.version)"
)"
registry_auth_path="$(
  node -e "const u=new URL(process.argv[1]); console.log('//' + u.host + u.pathname.replace(/\\/*$/, '/') + ':')" "$registry_url"
)"

npmrc="$(mktemp)"
trap 'rm -f "$npmrc"' EXIT
{
  echo "registry=${registry_url}"
  echo "always-auth=true"
  if [[ -n "$token" && "$token" != "REPLACE_ME" ]]; then
    echo "${registry_auth_path}_authToken=${token}"
  else
    password_b64="$(node -e "console.log(Buffer.from(process.argv[1]).toString('base64'))" "$password")"
    echo "${registry_auth_path}username=${username}"
    echo "${registry_auth_path}_password=${password_b64}"
    echo "${registry_auth_path}email=${email}"
  fi
} > "$npmrc"

if npm view "${package_name}@${package_version}" version --userconfig "$npmrc" --registry "$registry_url" >/dev/null 2>&1; then
  echo "${package_name}@${package_version} already exists in Yunxiao Packages; skip npm package publish."
  exit 0
fi

echo "${package_name}@${package_version} is not present in Yunxiao Packages yet; publishing local package directory ${package_dir}."
(
  cd "$package_dir"
  npm publish . --userconfig "$npmrc" --registry "$registry_url"
)
