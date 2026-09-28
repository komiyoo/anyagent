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
2. Update install and consumer docs:
   - README Yunxiao Packages PyPI installation guidance
   - downstream examples in `anyagent-apps` when startup behavior changes
3. Run local verification:
   - `uv lock --project packages/anyagent`
   - `uv run --project packages/anyagent pytest tests -q`
   - `uv build --project packages/anyagent`
4. Verify built metadata:
   - wheel and sdist report `Name: anyagent`
   - wheel installs the `anyagent` CLI entrypoint
5. Commit release changes to `main`.
6. Push the release commit to GitHub `main`:
   - repository: `https://github.com/Lyrik-AI/AnyAgent`
   - `origin` is that GitHub repository
7. Only after GitHub `main` contains the bumped version, create or move the matching git tag:
   - `git tag -f vX.Y.Z`
   - `git push --force https://github.com/Lyrik-AI/AnyAgent.git vX.Y.Z`
8. GitHub Actions publishes the Python package to Yunxiao Packages:
   - workflow: `.github/workflows/ci.yml`
   - job `publish-packages` runs only for a push to `main`, and only after `offline-quality` succeeds
   - it builds `packages/anyagent/dist/` with `bash scripts/ci/build_release_artifacts.sh`
   - pytest regressions and offline smokes stay in `offline-quality`; the publish job does not repeat them
   - the job calls `scripts/notify_release_start.py` before building; notification is skipped when `FEISHU_RELEASE_WEBHOOK_URL` is unset
   - publishing uses the dedicated Packages PyPI repository `anyagent`
   - create the dedicated Yunxiao Packages PyPI repository before enabling publish; do not reuse the existing `lyriktrip` / `lyra-python-sdk` repository
   - set `ANYAGENT_PYPI_REPOSITORY_URL` to the repository URL if the repo id is not exactly `anyagent`
   - keep `TWINE_PASSWORD` as a GitHub Actions secret
   - set `FEISHU_RELEASE_WEBHOOK_URL` as a GitHub Actions secret when notifications are required
   - set `FEISHU_RELEASE_WEBHOOK_SECRET` as a GitHub Actions secret when the Feishu bot enables signature verification
   - the workflow sets `ANYAGENT_PUBLISH_REQUIRED=1`, so a missing credential fails the job
   - `scripts/publish-yunxiao-pypi.sh` probes whether the exact target version already exists before uploading
9. Verify the published artifacts:
   - install from Yunxiao Packages PyPI in a clean environment
   - run `anyagent --help`
   - run `anyagent serve --help`
10. Update downstream consumers if needed:
   - `anyagent-apps/config/service-stack.example.toml`
   - `anyagent-apps/docs/service-stack-guide.md`
   - `anyagent-apps/examples/*`

## Notes

- Release source of truth is GitHub: `https://github.com/Lyrik-AI/AnyAgent`.
- Yunxiao Flow pipeline `4972656` (`anyagent build`) is retired. `.yunxiao/flow.anyagent.yml` has no Codeup push trigger. Do not turn that trigger back on.
- `publish-packages` sends a Feishu notification when configured, builds the Python distributions with `scripts/ci/build_release_artifacts.sh` on a GitHub-hosted runner, and publishes them to Yunxiao Packages PyPI.
- `sdks/typescript/` stays in the repo for Studio's `file:` typecheck dependency and for the checked-in protocol schema baseline. Release CI does not build or publish it.
- `scripts/notify_release_start.py` skips notification when `FEISHU_RELEASE_WEBHOOK_URL` is unset; when it is set, a failed Feishu response fails the job before package construction.
- `anyagent-apps` consumes the installed/published Python `anyagent` package; it does not publish the SDK.
- The publish job installs build tools from `https://pypi.org/simple`.
- Consumers install from the PyPI-compatible Yunxiao Packages repository using the distribution name `anyagent`.
- Twine upload uses `TWINE_REPOSITORY_URL`, `TWINE_USERNAME`, and `TWINE_PASSWORD`. The publish script defaults the first two; `TWINE_PASSWORD` comes from the GitHub Actions secret.
- `scripts/publish-yunxiao-pypi.sh` is the canonical publish command.
