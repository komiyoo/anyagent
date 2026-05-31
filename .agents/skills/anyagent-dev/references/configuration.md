# Configuration

Use this reference when changing `.anyagent/`, agent behavior, tools, skills, MCP, sandbox, models, or credentials.

## Agent Pack Files

Minimal agent pack:

```text
.anyagent/agents/<agent_id>/
  agent.yaml
  AGENTS.md
  mcp.json
```

`agent_id` must match `[a-zA-Z0-9_.-]{1,64}`.

## agent.yaml

Common fields:

```yaml
exposed: true
model:
  default: fast
tools:
  requested_tool_names:
    - core.web_fetch
  cli:
    - name: app.demo
      description: Run the repo's controlled CLI entrypoint.
      cwd: repo
      allow_command_prefixes:
        - npm run
      env:
        inherit: none
        set:
          NODE_ENV: development
      credentials:
        - credential_id: cred_demo_cli
          ref_kind: api_key
          injection_target: env:API_TOKEN
skills:
  default_selected:
    - repo-helper
  disabled_paths: []
sandbox:
  mode: "disabled"
multiagent:
  spawn_allow_agent_ids: []
```

Rules:

- `exposed: true` allows external `/v1/responses` calls to select this agent.
- `model.default` names a workspace `models.yaml` alias.
- `tools.requested_tool_names` is a desired exposure list; Tool Runtime manifest remains authoritative.
- `tools.cli` declares controlled CLI profiles. Each profile becomes a `kind="command"` tool automatically; do not duplicate it in `requested_tool_names`.
- CLI profile `allow_command_prefixes` is optional, but interpreter-shell tokens such as `bash`, `sh`, `python`, `node`, `sudo`, `-c`, and `-lc` are rejected by schema validation.
- CLI profile `env.set` must not contain secret-looking keys; inject secrets through Credential Vault targets like `env:NAME` or `file:relative/path` instead.
- `skills.default_selected` may contain skill names or stable skill paths.
- `sandbox.mode` is cold-start-sensitive. Restart the server after changing it.
- `multiagent.spawn_allow_agent_ids` is empty by default, meaning no child agents may be spawned.

## models.yaml

`anyagent config init` writes model/provider config at workspace root:

```yaml
default_model: fast
models:
  fast:
    provider: openai
    model: gpt-4o-mini
providers:
  openai:
    kind: openai
    api_key_env: OPENAI_API_KEY
```

Keep provider secrets in env vars or managed secrets, not literal YAML.

## AGENTS.md

Use workspace `AGENTS.md` for repo-wide behavior. Use agent-level `AGENTS.md` for persona, tool discipline, output style, and domain workflow. These files guide model behavior only; they are not authorization policy.

## Skills

Repo skill path:

```text
.anyagent/skills/<skill-name>/SKILL.md
```

Agent-local skill path:

```text
.anyagent/agents/<agent_id>/skills/<skill-name>/SKILL.md
```

Every skill needs frontmatter:

```markdown
---
name: repo-helper
description: Use when ...
---
```

Optional UI metadata lives at `agents/openai.yaml`. Use `dependencies.tools[]` when the skill needs Tool Runtime tools to become visible when selected.

## MCP

`mcp.json` should use credential references, not plaintext tokens:

```json
{
  "mcpServers": {
    "bocha-mcp": {
      "url": "https://mcp.bochaai.com/mcp",
      "transport": "streamable_http",
      "auth": {
        "credential_id": "cred_bocha_mcp",
        "ref_kind": "bearer_token",
        "injection": "header:Authorization",
        "format": "Bearer {value}"
      }
    }
  }
}
```

For stdio MCP servers, prefer explicit `command`, `args`, and `cwd`.

The `credential_id` must match a reference created via the Admin API, and `ref_kind` must match that reference's `kind` (see Credentials below).

## Tools And Plugins

Use built-in tools by adding names to `requested_tool_names`, for example `core.web_fetch` or `exec`.

For command execution that should stay within a narrow repo workflow, prefer `tools.cli` over raw `exec`. CLI profiles support:

- per-profile `cwd` and timeout
- constrained environment inheritance (`core` / `none` / `all`)
- Credential Vault injection to `env:*` or `file:*`
- the same command-stage events as other `kind="command"` tools

Custom business tools belong in Tool Runtime plugins and should normally use the `app.*` namespace. A generated demo plugin under `plugins/demo/` is inactive until the Tool Runtime loads it and the target agent requests its tool name.

## Credentials

The vault holds secrets server-side; agents and config files only ever reference a `credential_id`. Set a reference with the Admin API and read the secret from an env var so it never lands in shell history or repo files:

```bash
ADMIN_API_KEY=admin-key anyagent credential set \
  --admin-url http://127.0.0.1:8787 \
  --admin-key admin-key \
  --id cred_bocha_mcp \
  --kind bearer_token \
  --scope agent \
  --agent-id main \
  --value-from-env BOCHA_MCP_TOKEN \
  --provider bocha
```

`anyagent credential list` / `delete` manage references without exposing plaintext; `anyagent credential import` loads several from a YAML file. The `--id` here must equal the `credential_id` used in `mcp.json` (or a plugin manifest), and `--kind` must match `ref_kind`. Use `--scope global|agent|session` to bound where the reference resolves. Use separate `AGENT_API_KEY`, `ADMIN_API_KEY`, and internal Tool Runtime key in deployed setups.

## Config Reload

Hot fields such as model/tools/skills can apply to later requests after hot reload. Cold fields such as `sandbox` and `storage` require process restart because they bind runtime resources.
