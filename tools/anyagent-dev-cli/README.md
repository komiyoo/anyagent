# anyagent-dev-cli

Repo-bound automation CLI for durable anyagent maintenance workflows.

## Install

```bash
npm --prefix tools/anyagent-dev-cli run install:local
anyagent-dev-cli doctor
```

The install command builds the TypeScript CLI and installs the repository
wrapper to `~/.local/bin/anyagent-dev-cli`. Override the target directory with
`ANYAGENT_DEV_CLI_INSTALL_DIR`.

```bash
ANYAGENT_DEV_CLI_INSTALL_DIR=/usr/local/bin npm --prefix tools/anyagent-dev-cli run install:local
```

## Output Policy

Default output is compact Markdown for agent and human reading. Pass `--json`
when another tool needs stable machine-readable output.

Commands that support `--json` return a stable envelope:

```json
{
  "ok": true,
  "data": {}
}
```

Errors under `--json` use:

```json
{
  "ok": false,
  "error": {
    "code": "error_code",
    "message": "short message"
  }
}
```

Do not include credentials or secret values in JSON output.

## Commands

```bash
anyagent-dev-cli doctor
anyagent-dev-cli version show
anyagent-dev-cli version bump 0.4.10 --dry-run
scripts/anyagent-dev-cli doctor
scripts/anyagent-dev-cli version show
scripts/anyagent-dev-cli version bump 0.4.10 --dry-run
scripts/anyagent-dev-cli doctor --json
scripts/anyagent-dev-cli version show --json
scripts/anyagent-dev-cli version bump 0.4.10 --dry-run --json
```

`version bump` updates all known framework version sources after first verifying
that their current values agree:

- `packages/anyagent/pyproject.toml`
- `packages/anyagent/src/anyagent/__init__.py`
- `packages/anyagent/src/anyagent/tool_runtime/__init__.py`
- `packages/anyagent/src/anyagent/server/app.py`
- `packages/anyagent/src/anyagent/tool_runtime/server.py`

## Roadmap

Promote other repeated repo workflows into this CLI as they stabilize:

- release readiness and build artifact checks
- GitHub Actions release status and Yunxiao Packages artifact lookup
- protocol schema export and diff wrappers
- docs guardrail and TODO evidence checks
