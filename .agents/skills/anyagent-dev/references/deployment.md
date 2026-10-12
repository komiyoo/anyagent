# Deployment

## One process

From the business repo:

```bash
anyagent serve --workspace .
```

`anyagent dev --workspace .` starts the same built-in server with local development defaults. Set provider keys in the environment or in `.env` (see `.env.example`). Do not commit `.env`.

`anyagent doctor --workspace .` is the check before serving.

## Storage

Built-in defaults already interpolate storage settings from the environment (`POSTGRES_DSN`, `DATABASE_URL`, `REDIS_DSN`, `STORAGE_PROFILE`, and the related variables in `packages/anyagent/src/anyagent/config/defaults.py`). Set those variables, or write the `storage` section in `.anyagent/anyagent.yaml` when no system or user layer has already set `storage`.

Apply schema changes with `anyagent storage migrate` (or `anyagent db migrate` for the Alembic entry). Check connectivity with `anyagent storage health`.

## Sandbox

`exec` runs inside the agent's sandbox. `local-unsafe` is for a trusted developer machine. `opensandbox` and `external` are the modes for anything else. Workspace `sandbox` in `.anyagent/anyagent.yaml` configures the backend (image, endpoint, API key placeholder). The agent's own `sandbox.mode` selects whether that agent may use it.

Restart the server after changing sandbox mode.

## Split processes

The built-in `anyagent serve` loads workspace plugins in-process. To split them:

```bash
anyagent tool-runtime serve --workspace .
anyagent agent-api serve --workspace .
```

Point the agent API at the tool runtime with `tool_runtime.base_url` and `tool_runtime.internal_key` in config (values may be `${VAR}` placeholders). Both processes need the same workspace so plugin roots and agent packs match.

Credentials are still resolved by the server. Use `anyagent credential list` to confirm ids, and `anyagent credential set` to write one. The CLI does not print secret values.

Further topology and threat boundaries: `docs/guides/deployment.md`, `docs/security/sandbox-security.md`, `docs/security/credential-vault.md`.
