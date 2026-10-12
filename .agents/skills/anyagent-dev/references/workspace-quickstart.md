# Workspace quickstart

`anyagent init` writes a minimal workspace through `anyagent.scaffold`. The generated tree does not include an empty `mcp.json`, a `.gitkeep`, a demo plugin, or a copy of the built-in model defaults.

## Layout

```text
AGENTS.md
.gitignore
.env.example
.anyagent/anyagent.yaml
.anyagent/schema/anyagent.schema.json
.anyagent/schema/agent.schema.json
.anyagent/schema/mcp.schema.json
.anyagent/agents/<agent_id>/AGENTS.md
.anyagent/agents/<agent_id>/agent.yaml
```

`anyagent.yaml` is often only the schema comment. That still loads: `models.default` stays the built-in alias `fast`. A provider, model, or base URL is written only when it differs from that default, as `models.default: <provider>:<model>` or `models.providers.<provider>.base_url`. `.env.example` lists the API key variables for the chosen provider, such as `OPENAI_API_KEY=`.

## Templates

| Template | Primary agent |
| --- | --- |
| `basic` | No tools, sandbox disabled |
| `coding-agent` | Requests `exec`, sandbox `local-unsafe` |
| `research-agent` | Requests `core.web_fetch`, sandbox disabled |
| `multi-agent-team` | Coordinator plus a research child (`core.web_fetch`) and a coding child (`exec`, `local-unsafe`). The coordinator's `multiagent.spawn_allow_agent_ids` lists those children |

When the primary id is not `main`, init also writes a thin `main` agent whose spawn list contains the primary id. The thin agent does not copy the primary tools or sandbox. An example skill is written only when requested, at `.anyagent/skills/example-skill/SKILL.md`, and selected on the template agents.

Check the result:

```bash
anyagent doctor --workspace .
anyagent config show --sources --workspace .
anyagent dev --workspace .
```

Add components with `anyagent add tool`, `anyagent add skill`, `anyagent add mcp`, or `anyagent add plugin`. See `references/configuration.md` for what each command writes.
