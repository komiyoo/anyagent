# Workspace Quickstart

Use this reference when creating a business repository or explaining how an anyagent workspace is laid out.

## Initialize

Prefer business initialization:

```bash
anyagent config init \
  --workspace . \
  --agent-id main \
  --model-alias fast \
  --model gpt-4o-mini \
  --provider openai
```

`--model-alias` is the name written into `models.yaml` and referenced by `agent.yaml`'s `model.default`; the two must match. The CLI default alias is `default` — these examples use `fast` consistently, so override or keep it, but stay consistent across both files.

Useful switches:

```bash
anyagent config init --workspace . --agent-id researcher --with-web-fetch
anyagent config init --workspace . --agent-id coder --with-exec
anyagent config init --workspace . --agent-id worker --tool core.web_fetch --tool exec --sandbox-mode local-unsafe
```

Use demo initialization for framework examples:

```bash
anyagent init --workspace . --template basic --with-example-skill
anyagent init --workspace . --template coding-agent
anyagent init --workspace . --template research-agent
anyagent init --workspace . --template multi-agent-team
```

## Generated Layout

```text
<workspace>/
  AGENTS.md
  models.yaml
  .anyagent/
    agents/
      main/
        agent.yaml
        AGENTS.md
        mcp.json
    skills/
  plugins/
    demo/
```

Key semantics:

- `AGENTS.md` at workspace root is the lower-priority workspace instruction layer.
- `.anyagent/agents/<agent_id>/AGENTS.md` is the higher-priority agent instruction layer.
- `.anyagent/agents/<agent_id>/agent.yaml` controls exposure, default model alias, requested tools, selected skills, sandbox, and multi-agent spawn policy.
- `.anyagent/agents/<agent_id>/mcp.json` describes MCP server connections and credential references.
- `.anyagent/skills/` contains repo-level skills shared across agents.
- `plugins/demo/` is generated as an inactive Tool Runtime plugin scaffold.

## First Validation

```bash
anyagent doctor --workspace .
anyagent agent list --workspace .
anyagent dev --workspace .
```

`anyagent dev` starts the built-in server with dev-friendly defaults and serves:

```text
API:    http://127.0.0.1:8787/v1
Studio: http://127.0.0.1:8787/ -> /studio/
```

For API-only local runs:

```bash
AGENT_API_KEY=dev-key anyagent serve --workspace . --port 8787 --no-studio
```

## First Request

`api_key` must equal the server's `AGENT_API_KEY` (or the `--api-key` passed to `serve`/`dev`). The examples below assume `AGENT_API_KEY=dev-key`.

OpenAI-compatible client (synchronous):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="dev-key")
response = client.responses.create(model="gpt-4o-mini", input="hello")
print(response.output_text)
```

AnyAgent SDK is async — every method is a coroutine, so call it under `asyncio.run` (or inside an existing event loop):

```python
import asyncio
from anyagent import AnyAgent

async def main():
    client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="dev-key")
    health = await client.health()
    print(health.agent_ids)
    skills = await client.skills.list(agent_id="main")
    print(skills)

asyncio.run(main())
```
