---
name: anyagent-dev
description: Guide agents that create or maintain business repositories, Agent Server workspaces, agent packs, skills, MCP integrations, Tool Runtime plugins, SDK clients, debugging flows, and deployment runbooks on top of anyagent. Use when a user asks to initialize an anyagent project, understand how the Agent Server runs, configure `.anyagent/`, develop an agent or skill, wire tools/MCP/credentials/sandbox/storage, debug `anyagent serve` or `anyagent dev`, deploy built-in or distributed runtime pieces, or update downstream business repositories after an anyagent framework change.
---

# AnyAgent Dev

Use this skill to build on anyagent from a business repository. Read the referenced file or the code it names before giving exact schemas or deployment advice.

## First move

1. Identify the target: a new workspace, an existing `.anyagent/` tree, agent behavior, a tool or plugin, an MCP server, a credential, debugging, or deployment.
2. From the business repo root:

```bash
anyagent doctor --workspace .
anyagent agent list --workspace .
```

If `anyagent` is not installed, read `.anyagent/` and say that CLI validation did not run. anyagent installs from GitHub source, not from PyPI; see `references/deployment.md`.

## Workflow

1. Edit `.anyagent/anyagent.yaml` for workspace settings and `.anyagent/agents/<agent_id>/agent.yaml` for one agent. Write only fields that differ from built-in defaults.
2. See which layer set each value:

```bash
anyagent config show --sources --workspace .
```

3. Validate the workspace:

```bash
anyagent doctor --workspace .
```

4. Generate glue code instead of hand-writing boilerplate:

```bash
anyagent add tool <name> --workspace .
anyagent add skill <name> --workspace .
anyagent add mcp <name> --workspace .
anyagent add plugin <name> --workspace .
```

5. Fill in the handler, skill body, or MCP server entry. Do not put secret values in those files.
6. Run the local server:

```bash
anyagent dev --workspace .
```

`anyagent serve --workspace .` is the same server without the dev defaults.

## Where to read next

- Generated layout and templates: `references/workspace-quickstart.md`
- Config files, interpolation, layers, credentials: `references/configuration.md`
- Doctor, plugin load failures, hot reload: `references/debugging.md`
- Serve, storage, sandbox, split processes: `references/deployment.md`
- Updating this skill after a framework change: `references/framework-maintenance.md`

Config code: `packages/anyagent/src/anyagent/config/schema.py`, `packages/anyagent/src/anyagent/config/defaults.py`, `packages/anyagent/src/anyagent/config/env.py`, `packages/anyagent/src/anyagent/config/loader.py`, `packages/anyagent/src/anyagent/config/agents.py`. Scaffold code: `packages/anyagent/src/anyagent/scaffold/`.

## Safety

- Do not store provider keys, MCP tokens, or customer secrets in the repo. Reference a `credential_id` or an environment variable.
- `local-unsafe` is for trusted local development. Use `opensandbox` or `external` when `exec` runs untrusted input.
- Requesting `exec` also requires a non-disabled sandbox mode on that agent.
