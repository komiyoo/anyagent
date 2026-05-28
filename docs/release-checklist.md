# anyagent Release Checklist

## Scope

Use this checklist whenever public SDK behavior, exported protocol models,
CLI commands, server runtime behavior, dependencies, packaging metadata, or
installation docs change.

## Checklist

1. Update `packages/anyagent/pyproject.toml`:
   - bump `[project].version`
   - keep the PyPI distribution name as `anyagent`
   - keep `packages/anyagent/src/anyagent/__init__.py`, server metadata, Tool Runtime metadata, and `packages/anyagent/uv.lock` aligned
2. Update `sdks/typescript/package.json` when the TypeScript SDK is part of the release:
   - bump `version`
   - keep the Yunxiao Packages NPM package name as `anyagent`
   - keep `sdks/typescript/package-lock.json` aligned
3. Update install and consumer docs:
   - README Yunxiao Packages PyPI installation guidance
   - README Yunxiao Packages NPM installation guidance when TypeScript SDK behavior changes
   - downstream examples in `anyagent-apps` when startup behavior changes
4. Run local verification:
   - `uv lock --project packages/anyagent`
   - `uv run --project packages/anyagent pytest tests -q`
   - `uv build --project packages/anyagent`
   - `npm --prefix sdks/typescript run smoke`
   - `npm --prefix sdks/typescript run pack:check`
5. Verify built metadata:
   - wheel and sdist report `Name: anyagent`
   - wheel installs the `anyagent` CLI entrypoint
   - npm tarball reports `name: anyagent` and contains `dist/`, generated protocol schemas, and declarations
6. Commit release changes to `main`.
7. Push the release commit to Codeup `main`.
8. Only after Codeup `main` contains the bumped version, create or move the matching git tag:
   - `git tag -f vX.Y.Z`
   - `git push --force codeup vX.Y.Z`
9. Let Yunxiao build and publish to Yunxiao Packages:
   - Yunxiao pipeline: `4972656` (`anyagent build`) builds `packages/anyagent/dist/` with `bash scripts/ci/build_release_artifacts.sh`
   - the pipeline sends a Feishu notification before tests/build via `scripts/notify_release_start.py`
   - the release build step should not run full pytest regressions; keep `scripts/ci/run_pytest_regressions.sh` and `scripts/ci/run_offline_smokes.sh` in the merge/CI gate before release
   - publishing uses the dedicated Packages PyPI repository `anyagent`
   - TypeScript SDK publishing uses the Packages NPM repository `npm-registry`
   - create the dedicated Yunxiao Packages PyPI repository before enabling publish; do not reuse the existing `lyriktrip` / `lyra-python-sdk` repository
   - set `ANYAGENT_PYPI_REPOSITORY_URL` to the repository URL if the repo id is not exactly `anyagent`
   - keep `TWINE_PASSWORD` as an encrypted pipeline variable
   - keep `NPM_PASSWORD` as an encrypted pipeline variable when using Yunxiao npm username/password auth
   - optionally override `ANYAGENT_NPM_REGISTRY_URL`, `ANYAGENT_NPM_USERNAME`, or `ANYAGENT_NPM_EMAIL` if Yunxiao changes the generated npmrc values
   - alternatively keep `ANYAGENT_NPM_TOKEN` or `NPM_TOKEN` as an encrypted pipeline variable when using token auth
   - keep `GITHUB_TOKEN` as an encrypted pipeline variable when GitHub mirror sync is required
   - set `FEISHU_RELEASE_WEBHOOK_URL` as an encrypted pipeline variable when notifications are required
   - set `FEISHU_RELEASE_WEBHOOK_SECRET` as an encrypted pipeline variable when the Feishu bot enables signature verification
   - the publish step calls `scripts/publish-yunxiao-pypi.sh`; it probes whether the exact target version already exists before uploading
   - the TypeScript publish step calls `scripts/publish-yunxiao-npm.sh`; it probes whether the exact target version already exists before uploading
10. Verify the published artifacts:
   - install from Yunxiao Packages PyPI in a clean environment
   - install `anyagent` from Yunxiao Packages NPM in a clean TypeScript project
   - run `anyagent --help`
   - run `anyagent serve --help`
11. Update downstream consumers if needed:
   - `anyagent-apps/config/service-stack.example.toml`
   - `anyagent-apps/docs/service-stack-guide.md`
   - `anyagent-apps/examples/*`

## Notes

- Source of truth is Codeup: `https://codeup.aliyun.com/63d476f8d14a7f379aa798da/anyagent.git`.
- Yunxiao pipeline `4972656` sends a Feishu pre-build notification, builds and verifies distributions from Codeup with `scripts/ci/build_release_artifacts.sh`, uploads `packages/anyagent/dist/` as a Flow artifact, syncs the current branch to GitHub when mirror variables are configured, publishes to Yunxiao Packages PyPI when `TWINE_PASSWORD` is configured, and publishes the TypeScript SDK to Yunxiao Packages NPM when npm credentials are configured.
- `scripts/notify_release_start.py` skips notification when `FEISHU_RELEASE_WEBHOOK_URL` is unset; when it is set, a failed Feishu response fails the build before package construction.
- `anyagent-apps` consumes the installed/published `anyagent` package; it does not publish the SDK.
- Yunxiao build uses the Aliyun PyPI mirror only for third-party dependency downloads.
- Yunxiao build and publish steps reuse dependency caches under `/root/.cache` (`/root/.cache/pip` and `/root/.cache/uv`), matching Yunxiao's default pipeline cache paths; avoid purging pip cache in the pipeline unless diagnosing a corrupted cache.
- The SDK pipeline runs on the prebuilt `linux/amd64` image `registry.cn-beijing.aliyuncs.com/lyriktrip/python:anyagent-ci-py312-amd64`, based on the current `python:3.12-slim-bookworm` patch release with build tooling and warm pip/uv caches for the anyagent test dependency set.
- Consumers install from the PyPI-compatible Yunxiao Packages repository using the distribution name `anyagent`.
- TypeScript consumers install from the NPM-compatible Yunxiao Packages repository using the package name `anyagent`.
- Twine upload uses `TWINE_REPOSITORY_URL`, `TWINE_USERNAME`, and encrypted `TWINE_PASSWORD`; the pipeline provides defaults for the first two.
- NPM upload defaults to the Yunxiao Packages `npm-registry` URL and supports either encrypted token auth (`ANYAGENT_NPM_TOKEN` / `NPM_TOKEN`) or username/password auth (`ANYAGENT_NPM_USERNAME` / `NPM_PASSWORD` / `ANYAGENT_NPM_EMAIL`).
- GitHub mirror sync uses `ANYAGENT_GITHUB_MIRROR_REPO` or `GITHUB_MIRROR_REPO`, encrypted `GITHUB_TOKEN`, optional `GITHUB_MIRROR_URL_PREFIX`, and optional branch/tag controls. The Yunxiao release pipeline sets `GITHUB_MIRROR_FORCE=true` because Codeup is the release source of truth and GitHub is a mirror target.
- The Cloudflare Open Proxy Worker at `proxy.cbotomo.com` is URL-forwarding style (`https://proxy.cbotomo.com/https://target/...`). It can be used by setting `GITHUB_MIRROR_URL_PREFIX=https://proxy.cbotomo.com`, in which case the mirror script sends GitHub auth with an HTTP header instead of embedding the token in the proxied URL.
- `scripts/publish-yunxiao-pypi.sh` is the canonical publish command for the pipeline.
- `scripts/publish-yunxiao-npm.sh` is the canonical TypeScript SDK publish command for the pipeline.
