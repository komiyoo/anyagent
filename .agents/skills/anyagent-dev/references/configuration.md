# Configuration

One config document: `.anyagent/anyagent.yaml`, validated by `WorkspaceConfig` in `packages/anyagent/src/anyagent/config/schema.py`. Agent packs live under `.anyagent/agents/<agent_id>/`. There is no `models.yaml`, no `secrets.yaml`, and no `*_env` field. A secret is an interpolated string or a `credential_id`. Older guides that still name those files or fields are stale for this subject.

## Files

| Path | Role |
| --- | --- |
| `.anyagent/anyagent.yaml` | Workspace models, server, storage, credentials, sandbox, plugins, observability |
| `.anyagent/schema/anyagent.schema.json` | JSON Schema for the workspace file |
| `.anyagent/agents/<agent_id>/agent.yaml` | Exposed flag, model, tools, skills, sandbox, spawn |
| `.anyagent/agents/<agent_id>/AGENTS.md` | Agent instructions. Required once the agent directory exists |
| `.anyagent/agents/<agent_id>/mcp.json` | That agent's MCP servers. Omit the file when there are none |
| `.anyagent/skills/<name>/SKILL.md` | Skill package. YAML frontmatter requires `name` and `description` |
| `.env.example` | Variable names for the chosen provider. Copy to `.env`; do not commit `.env` |

The first line of each YAML file is a yaml-language-server schema comment pointing at `.anyagent/schema/`. `mcp.json` may set `$schema` to the same directory.

Write a field only when it differs from the built-in default. The built-in model is the alias `fast` (provider `openai`, model `gpt-4o-mini`). A model value is either an alias or `provider:model` (for example `anthropic:claude-sonnet-4-5`). A provider that is not one of `openai`, `openai_chat`, `anthropic`, or `gemini` must be declared under `models.providers` with a `kind`.

```yaml
# yaml-language-server: $schema=./schema/anyagent.schema.json
models:
  default: anthropic:claude-sonnet-4-5
plugins:
  roots:
    - plugins
```

```yaml
# yaml-language-server: $schema=../../schema/agent.schema.json
model:
  default: fast
tools:
  requested_tool_names:
    - exec
sandbox:
  mode: local-unsafe
skills:
  default_selected:
    - review
```

`model: fast` on the agent is optional while the workspace default is already `fast`. `agent.yaml` `sandbox.mode` is the per-agent exec sandbox. It is separate from the workspace `sandbox` section.

## Interpolation

`packages/anyagent/src/anyagent/config/env.py` expands `${VAR}` and `${VAR:-default}` after the layers merge. A missing variable with no default becomes an empty string, and empty strings are removed. List-shaped fields that are still a comma-separated string (`plugins.roots`, `tool_runtime.plugin_roots`, `server.cors_origins`) are split on commas.

The server reads `.env` and `.env.local` from the workspace before interpolation. Do not add a second dotenv loader.

## Layers

`load_effective_config` merges in this order. Later layers replace lists and scalars; dicts merge.

1. Built-in defaults (`packages/anyagent/src/anyagent/config/defaults.py`)
2. System `/etc/anyagent/anyagent.yaml`, or `$SYSTEM_CONFIG_DIR/anyagent.yaml`
3. User `~/.anyagent/anyagent.yaml`, or `$USER_CONFIG_DIR/anyagent.yaml`
4. Workspace `.anyagent/anyagent.yaml`
5. CLI overrides

`anyagent config show --sources` prints the winning layer for each leaf. A workspace file cannot override `sandbox.mode` or `storage` when the system or user layer already set that path. CLI overrides can. Built-in defaults do not count as that higher-trust layer, so a workspace may set `storage` when no system or user file has.

Agent packs merge the same way: system, user, then workspace `.anyagent/agents/<agent_id>/`.

## Credentials

`credentials` in `.anyagent/anyagent.yaml`:

- `backend`: `none`, `env`, `file`, `db`, `vault`, or `infisical`
- `writable`: whether the Admin Credential API may create or update credentials
- `runtime_env`: list of `{name, credential_id, kind}` entries injected into the process for a run

MCP servers do not store the secret. Set `auth.credential_id` and let the server resolve it:

```json
{
  "mcpServers": {
    "docs": {
      "url": "https://example.com/mcp",
      "auth": {"credential_id": "cred_docs"}
    }
  }
}
```

A stdio server uses `command` and `args` instead of `url`, not both. Create credentials with `anyagent credential set` against a running server, or point `credentials.backend` at env, file, db, vault, or infisical.

## Tools, skills, plugins

- Built-in tool names (`exec`, `core.web_fetch`, and the other reserved names) go in `tools.requested_tool_names`. They are not generated as plugins.
- `anyagent add tool <name>` writes `plugins/<name>/` (`plugin.json` plus `plugin.py`), appends `plugins` to `plugins.roots`, and requests the public tool name. A bare name such as `echo` becomes `app.echo`.
- `anyagent add plugin <name>` writes a skeleton and registers the plugin root. It does not request a tool.
- `anyagent add skill <name>` writes `.anyagent/skills/<name>/SKILL.md` and appends `<name>` to the agent's `skills.default_selected`.
- `anyagent add agent <name>` writes an agent pack. Pass `exposed=false` when the agent should be hidden from the default route and used only as a spawn target.
