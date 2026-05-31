# Debugging

Use this reference when `anyagent dev`, `anyagent serve`, SDK calls, prompt injection, skills, tools, MCP, or storage behavior is unclear.

## Triage Order

1. Validate workspace:
   ```bash
   anyagent doctor --workspace .
   anyagent agent list --workspace . --json
   ```
2. Start with explicit keys:
   ```bash
   AGENT_API_KEY=dev-key ADMIN_API_KEY=admin-key anyagent serve --workspace . --port 8787
   ```
3. Confirm the selected agent:
   - External calls use `metadata.agent_id`.
   - Default agent is `main`.
   - The selected agent must exist and be `exposed: true`.
4. Inspect prompt/config assembly through SDK helpers where available. The SDK is async, so await every call (here under `asyncio.run`):
   ```python
   import asyncio
   from anyagent import AnyAgent

   async def main():
       client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="dev-key")
       print(await client.agents.list())
       print(await client.skills.list(agent_id="main"))

   asyncio.run(main())
   ```

## Common Failures

`main` missing or not exposed:

- Ensure `.anyagent/agents/main/agent.yaml` exists.
- Set `exposed: true`.
- Re-run `anyagent doctor --workspace .`.

Tool not visible:

- Check `.anyagent/agents/<agent_id>/agent.yaml` `tools.requested_tool_names`.
- Check selected skill dependencies if the tool should come from a skill.
- Remember Tool Runtime manifest is authoritative; requested names are not a permission bypass.
- For plugin tools, ensure the Tool Runtime process actually loaded the plugin root.

Skill not injected:

- Ensure `SKILL.md` frontmatter has `name` and `description`.
- Check `skills.default_selected`, explicit request `metadata.skills`, or `$skill-name` mention.
- Check `skills.disabled_paths`.
- Check duplicate skill names across roots.

MCP tool missing:

- Validate `.anyagent/agents/<agent_id>/mcp.json`.
- Confirm transport (`streamable_http`, SSE/HTTP, or stdio) and credential reference.
- Verify the referenced credential is actually registered, and that `mcp.json` `credential_id`/`ref_kind` match the `--id`/`--kind` used at `credential set` time:
  ```bash
  ADMIN_API_KEY=admin-key anyagent credential list --admin-url http://127.0.0.1:8787 --admin-key admin-key
  ```
- A failed MCP server should produce lifecycle stage events and may be skipped without blocking all tools.

Unexpected config after edits:

- Model/tools/skills are hot fields for later requests.
- Sandbox/storage are cold fields and require server restart.
- Layer priority is system -> user -> workspace -> session.

Storage or replay issues:

```bash
ADMIN_API_KEY=admin-key anyagent storage health --admin-key admin-key
POSTGRES_DSN=postgresql://... anyagent storage migrate
```

If using external storage, verify `STORAGE_MODE`, `EVENT_STORE_BACKEND`, `RUN_STORE_BACKEND`, `SESSION_STORE_BACKEND`, `POSTGRES_DSN`, and `REDIS_DSN`.

## Useful Evidence To Return

- Workspace path and selected `agent_id`.
- Output summary from `anyagent doctor`.
- Relevant file paths: `agent.yaml`, `AGENTS.md`, `mcp.json`, skill path, plugin manifest.
- Server command and key env var names, with values redacted.
- Response id, session key, trace id, and stage event types when available.
