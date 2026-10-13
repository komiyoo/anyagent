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
   - source installation guidance in `docs/guides/deployment.md`
   - quickstart commands in `docs/guides/getting-started.md` when CLI or startup behavior changes
   - `.agents/skills/anyagent-dev/` when workspace, CLI, or deployment behavior that business repos rely on changes
3. Run local verification:
   - `uv lock --project packages/anyagent`
   - `uv run --project packages/anyagent pytest tests -q`
   - `bash scripts/ci/build_release_artifacts.sh` (builds wheel/sdist and checks metadata; nothing is uploaded)
4. Verify built metadata:
   - wheel and sdist report `Name: anyagent`
   - wheel installs the `anyagent` CLI entrypoint
5. Commit release changes to `main`.
6. After the user confirms, push the release commit to GitHub `main`:
   - repository: `https://github.com/komiyoo/anyagent` (`origin`)
7. Only after GitHub `main` contains the bumped version, create or move the matching git tag:
   - `git tag -f vX.Y.Z`
   - `git push --force origin vX.Y.Z`
8. Verify the release:
   - the `anyagent-ci` run for that push is green (`offline-quality`)
   - in a clean environment, install from source: `uv pip install "anyagent @ git+https://github.com/komiyoo/anyagent.git@vX.Y.Z#subdirectory=packages/anyagent"`
   - run `anyagent --help`
   - run `anyagent serve --help`

## Notes

- Release source of truth is GitHub: `https://github.com/komiyoo/anyagent`.
- The project currently ships as source only. CI does not build or upload packages to any registry. A release is a version bump on `main` plus the matching `vX.Y.Z` tag.
- Business repos pin a tag or commit in their dependency, for example `anyagent @ git+https://github.com/komiyoo/anyagent.git@vX.Y.Z#subdirectory=packages/anyagent`, and own their own upgrades.
- Yunxiao Flow pipeline `4972656` (`anyagent build`) is retired. `.yunxiao/flow.anyagent.yml` has no Codeup push trigger. Do not turn that trigger back on.
- Workflow name is `anyagent-ci`. Keep `.github/workflows/ci.yml` enabled. A disabled workflow does not run on push.
- `sdks/typescript/` stays in the repo for Studio's `file:` typecheck dependency and for the checked-in protocol schema baseline. It is not built or published.
- This repo ships no example application.
- `scripts/publish-yunxiao-pypi.sh` and `scripts/notify_release_start.py` are kept for a possible return to registry publishing. No workflow calls them now. Bringing package publishing back needs a new CI job, a registry secret, and updates to this checklist and `docs/architecture/engineering/ci-pipeline.md`.
