# Deployment

Use this reference when planning how to run anyagent locally, in a single process, or as split Agent API and Tool Runtime services.

## Built-In Single Process

Best for local development, demos, and simple single-node services:

```bash
AGENT_API_KEY=agent-key \
ADMIN_API_KEY=admin-key \
OPENAI_API_KEY=sk-... \
anyagent serve --workspace . --host 0.0.0.0 --port 8787
```

Characteristics:

- Built-in FastAPI server.
- In-process Tool Runtime.
- Built-in Studio unless `--no-studio` is passed.
- In-memory storage by default unless external backends are configured.

## Dev Server

```bash
anyagent dev --workspace .
```

Use for local loops. It uses dev-friendly defaults and exposes Studio.

## External Storage

Install extras as needed:

```bash
uv pip install 'anyagent[postgres,redis]'
```

Run migration and serve:

```bash
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
anyagent storage migrate

POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
REDIS_DSN=redis://127.0.0.1:6379/0 \
REDIS_NAMESPACE=anyagent \
POSTGRES_SCHEMA_POLICY=migrate \
STORAGE_MODE=external \
EVENT_STORE_BACKEND=external \
RUN_STORE_BACKEND=external \
SESSION_STORE_BACKEND=external \
anyagent serve --workspace . --session-lock-backend redis
```

## Split Runtime

Use split mode when tool execution needs independent scaling, isolation, plugin loading, or internal network boundaries.

Tool Runtime:

```bash
anyagent tool-runtime serve \
  --workspace . \
  --plugin-root plugins \
  --internal-key tool-internal-key \
  --admin-key admin-key
```

Agent API:

```bash
anyagent agent-api serve \
  --workspace . \
  --api-key agent-key \
  --tool-runtime-internal-key tool-internal-key
```

Keep `AGENT_API_KEY`, `ADMIN_API_KEY`, and Tool Runtime internal key distinct.

## Sandbox

Use `local-unsafe` only for trusted local development:

```yaml
tools:
  requested_tool_names:
    - exec
sandbox:
  mode: "local-unsafe"
```

For production command execution, use `opensandbox` or `external` and document network egress policy, filesystem persistence, and credential isolation.

CLI profile note:

- `tools.cli` works with `local-unsafe`, `opensandbox`, and `external` manifest routing.
- Credential injection to `env:*` / `file:*` is now implemented for `local-unsafe` and `opensandbox`.
- For `opensandbox`, file targets are uploaded through the execd `/files/upload` path before command execution; they are still declared as relative paths in `agent.yaml`.
- If a profile is exposed on a public agent and still uses `local-unsafe`, `anyagent doctor --workspace .` will emit a warning.

## Observability

Structured logs:

```bash
ANYAGENT_LOG_FORMAT=json anyagent serve --workspace .
```

Optional HTTP collector:

```bash
ANYAGENT_OBSERVABILITY_HTTP_URL=https://collector.example.com/ingest \
anyagent serve --workspace .
```

Studio consumes typed observability APIs and telemetry store data; do not design deployments around scraping raw log files.
