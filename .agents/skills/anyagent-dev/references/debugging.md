# Debugging

## See the effective config

```bash
anyagent config show --sources --workspace .
anyagent doctor --workspace .
anyagent agent list --workspace .
```

`config show --sources` answers which layer won: default, system, user, workspace, or cli. If a workspace edit seems ignored, check whether system or user config already set `sandbox.mode` or `storage`. Those paths cannot be overridden by the workspace file.

Doctor should pass before `anyagent dev` or `anyagent serve`. A catalog error usually means an agent directory is missing `AGENTS.md`, `agent.yaml` is not a mapping, or `mcp.json` is invalid. An MCP server needs `url` or `command`, not both, and no plaintext secret.

## Skills and plugins

A skill is loadable when `.anyagent/skills/<name>/SKILL.md` has YAML frontmatter with `name` and `description`, and the agent lists that name under `skills.default_selected`.

A generated tool plugin is loadable when all of these hold:

- `plugins/<name>/plugin.json` has `entrypoint` `plugin.py:register`
- `register` calls `registerTool` for host kind `gateway` and `tool_runtime`
- `plugins.roots` includes `plugins`
- the agent's `tools.requested_tool_names` contains the public tool name (`app.<name>` for a bare name)

`anyagent add tool` does this wiring. Replace the handler body after generation. `anyagent plugin catalog` lists plugins loaded by a running server's Admin API.

## Reload

The next request picks up changes to an agent's model and `tools.requested_tool_names`. A sandbox mode change is ignored until the process restarts; the server logs that a restart is required and keeps the previous catalog. Restart `anyagent serve` or `anyagent dev` after changing sandbox mode or `plugins.roots`.

## Runs

Use the server logs and Stage Events for a single response. Stable ids are `agent_id`, `response_id`, `tool_call_id`, and `seq`. Credential values do not belong in events or in the repo. For a failing tool, read the handler and the tool name in `agent.yaml` before changing the model.
