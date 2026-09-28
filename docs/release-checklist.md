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
   - `git push --force origin vX.Y.Z`
8. GitHub Actions publishes the Python package to Yunxiao Packages:
   - workflow: `.github/workflows/ci.yml`
   - job `publish-packages` runs only for a push to `main`, and only after `offline-quality` succeeds
   - it builds `packages/anyagent/dist/` with `bash scripts/ci/build_release_artifacts.sh`
   - pytest regressions and offline smokes stay in `offline-quality`; the publish job does not repeat them
   - the job calls `scripts/notify_release_start.py` before building; notification is skipped when `FEISHU_RELEASE_WEBHOOK_URL` is unset
   - publishing uses the Packages PyPI repository `anyagent` at `https://packages.aliyun.com/63d476f8d14a7f379aa798da/pypi/anyagent`
   - do not publish into the `lyriktrip` / `lyra-python-sdk` repository
   - keep `TWINE_PASSWORD` as a GitHub Actions secret on `Lyrik-AI/AnyAgent`
   - set `FEISHU_RELEASE_WEBHOOK_URL` as a GitHub Actions secret when notifications are required
   - set `FEISHU_RELEASE_WEBHOOK_SECRET` as a GitHub Actions secret when the Feishu bot enables signature verification
   - the workflow sets `ANYAGENT_PUBLISH_REQUIRED=1`, so a missing `TWINE_PASSWORD` fails the job
   - `scripts/publish-yunxiao-pypi.sh` probes whether the exact target version already exists before uploading
   - when that version is already present, the job succeeds and logs `already exists in Yunxiao Packages; skip package publish.` This does not upload a new artifact
9. Verify the publish result:
   - the `anyagent-ci` run is green, including `publish-packages`
   - a new version appears in the Packages PyPI repository `anyagent`
   - an unchanged version shows the skip log above and leaves the existing artifact in place
   - install the published version from Yunxiao Packages PyPI in a clean environment when the version changed
   - run `anyagent --help`
   - run `anyagent serve --help`
10. Update downstream consumers if needed:
   - `anyagent-apps/config/service-stack.example.toml`
   - `anyagent-apps/docs/service-stack-guide.md`
   - `anyagent-apps/examples/*`

## Notes

- Release source of truth is GitHub: `https://github.com/Lyrik-AI/AnyAgent`.
- Yunxiao Flow pipeline `4972656` (`anyagent build`) is retired. `.yunxiao/flow.anyagent.yml` has no Codeup push trigger. Do not turn that trigger back on.
- Workflow name is `anyagent-ci`. Keep `.github/workflows/ci.yml` enabled. A disabled workflow does not run on push.
- `publish-packages` builds the Python distributions with `scripts/ci/build_release_artifacts.sh` on a GitHub-hosted runner. It uploads to Yunxiao Packages only when that exact version is absent. An existing version is a successful skip.
- Feishu notification runs only when `FEISHU_RELEASE_WEBHOOK_URL` is set. It is currently unset, so the notify step logs a skip and continues.
- `sdks/typescript/` stays in the repo for Studio's `file:` typecheck dependency and for the checked-in protocol schema baseline. Release CI does not build or publish it.
- `scripts/notify_release_start.py` skips notification when `FEISHU_RELEASE_WEBHOOK_URL` is unset; when it is set, a failed Feishu response fails the job before package construction.
- `anyagent-apps` consumes the installed/published Python `anyagent` package; it does not publish the SDK.
- The publish job installs build tools from `https://pypi.org/simple`.
- Consumers install from the PyPI-compatible Yunxiao Packages repository using the distribution name `anyagent`.
- Twine upload uses `TWINE_REPOSITORY_URL`, `TWINE_USERNAME`, and `TWINE_PASSWORD`. The publish script defaults the first two; `TWINE_PASSWORD` comes from the GitHub Actions secret.
- `scripts/publish-yunxiao-pypi.sh` is the canonical publish command.
