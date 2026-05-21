# anyagent Release Checklist

## Scope

Use this checklist whenever public SDK behavior, exported protocol models,
CLI commands, server runtime behavior, dependencies, packaging metadata, or
installation docs change.

## Checklist

1. Update `packages/anyagent/pyproject.toml`:
   - bump `[project].version`
   - keep the PyPI distribution name as `anyagent`
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
6. Push the release commit to Codeup `main`.
7. Only after Codeup `main` contains the bumped version, create or move the matching git tag:
   - `git tag -f vX.Y.Z`
   - `git push --force codeup vX.Y.Z`
8. Let Yunxiao build and publish to Yunxiao Packages PyPI:
   - Yunxiao pipeline: `4972656` (`anyagent build`) builds and verifies `packages/anyagent/dist/`
   - the pipeline sends a Feishu notification before tests/build via `scripts/notify_release_start.py`
   - publishing uses the Packages PyPI repository `lyriktrip`
   - keep `TWINE_PASSWORD` as an encrypted pipeline variable
   - set `FEISHU_RELEASE_WEBHOOK_URL` as an encrypted pipeline variable when notifications are required
   - set `FEISHU_RELEASE_WEBHOOK_SECRET` as an encrypted pipeline variable when the Feishu bot enables signature verification
   - the publish step calls `scripts/publish-yunxiao-pypi.sh`; it probes whether the exact target version already exists before uploading
9. Verify the published artifacts:
   - install from Yunxiao Packages PyPI in a clean environment
   - run `anyagent --help`
   - run `anyagent serve --help`
10. Update downstream consumers if needed:
   - `anyagent-apps/apps/*/pyproject.toml`
   - `anyagent-apps/config/service-stack.example.toml`
   - `anyagent-apps/docs/service-stack-guide.md`

## Notes

- Source of truth is Codeup: `https://codeup.aliyun.com/63d476f8d14a7f379aa798da/anyagent.git`.
- Yunxiao pipeline `4972656` sends a Feishu pre-build notification, builds and verifies distributions from Codeup, uploads `packages/anyagent/dist/` as a Flow artifact, and publishes to Yunxiao Packages PyPI when `TWINE_PASSWORD` is configured.
- `scripts/notify_release_start.py` skips notification when `FEISHU_RELEASE_WEBHOOK_URL` is unset; when it is set, a failed Feishu response fails the build before package construction.
- `anyagent-apps` consumes the installed/published `anyagent` package; it does not publish the SDK.
- Yunxiao build uses the Aliyun PyPI mirror only for third-party dependency downloads.
- Consumers install from the PyPI-compatible Yunxiao Packages repository using the distribution name `anyagent`.
- Twine upload uses `TWINE_REPOSITORY_URL`, `TWINE_USERNAME`, and encrypted `TWINE_PASSWORD`; the pipeline provides defaults for the first two.
- `scripts/publish-yunxiao-pypi.sh` is the canonical publish command for the pipeline.
