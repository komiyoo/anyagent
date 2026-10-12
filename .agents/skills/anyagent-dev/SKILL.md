---
name: anyagent-dev
description: Guide agents that create or maintain business repositories, Agent Server workspaces, agent packs, skills, MCP integrations, Tool Runtime plugins, SDK clients, debugging flows, and deployment runbooks on top of anyagent. Use when a user asks to initialize an anyagent project, understand how the Agent Server runs, configure `.anyagent/`, develop an agent or skill, wire tools/MCP/credentials/sandbox/storage, debug `anyagent serve` or `anyagent dev`, deploy built-in or distributed runtime pieces, or update downstream business repositories after an anyagent framework change.
---

# AnyAgent Dev

Use this skill as the repo-level onboarding and implementation guide for building on anyagent from a business repository. Prefer current repository truth over memory: read the referenced docs or code before giving exact commands, schemas, or deployment advice.

## First Move

1. Identify the target shape:
   - New business workspace or repo.
   - Existing `.anyagent/` workspace configuration.
   - Agent behavior change (`AGENTS.md`, `agent.yaml`, skills, MCP).
   - Tool Runtime/plugin work.
   - SDK/client integration.
   - Runtime debugging or deployment.
   - Framework change that may require this skill to be updated.
2. Run local discovery from the relevant repo root:
   ```bash
   anyagent doctor --workspace .
   anyagent agent list --workspace .
   ```
   If `anyagent` is not installed, inspect `.anyagent/` directly and state that CLI validation could not run.
3. For exact framework behavior, follow these source paths in this repo:
   - Workspace and CLI: `docs/guides/getting-started.md`, `packages/anyagent/src/anyagent/cli/`
   - Serving, storage, observability, credential backends, plugins: `docs/guides/deployment.md`
   - Agent packs/config merge: `docs/architecture/runtime/agent-packs-and-runtime-config.md`, `packages/anyagent/src/anyagent/config/agents.py`
   - Server and SDK API: `docs/architecture/api/responses-api-sdk-and-server.md`
   - Agent loop / models.yaml: `docs/architecture/runtime/agent-loop.md`
   - Skills: `docs/architecture/skills/skills-dynamic-disclosure.md`
   - Tool Runtime: `docs/architecture/tool-runtime/tool-runtime-contract.md`
   - Security/sandbox/credentials: `docs/security/security-threat-model.md`

## Choose The Reference

- Initialize or explain a business repo: read `references/workspace-quickstart.md`.
- Configure agents, models, skills, MCP, sandbox, or credentials: read `references/configuration.md`.
- Debug server runs, prompt injection, tools, events, or SDK calls: read `references/debugging.md`.
- Plan local/prod deployment or split Agent API from Tool Runtime: read `references/deployment.md`.
- Change anyagent framework behavior or docs: read `references/framework-maintenance.md`.

## Default Workflow

For a new business repo, use `anyagent init`. `--template` selects the workspace shape. `--provider` and `--model` record the model selection:

```bash
anyagent init --workspace . --agent-id main --template basic --provider openai --model gpt-4o-mini
anyagent doctor --workspace .
anyagent dev --workspace .
```

Templates are `basic`, `coding-agent`, `research-agent`, and `multi-agent-team`. Add a component after init:

```bash
anyagent add agent researcher --workspace .
anyagent add skill repo-helper --workspace . --agent-id main
```

After initialization, edit the smallest relevant surface:

- `.anyagent/agents/<agent_id>/AGENTS.md` for agent behavior and operating rules.
- `.anyagent/agents/<agent_id>/agent.yaml` for model default, requested tools, skills, sandbox, and spawn policy.
- `.anyagent/agents/<agent_id>/mcp.json` for MCP servers and credential references.
- `.anyagent/skills/<skill-name>/SKILL.md` for reusable agent capabilities.
- `plugins/<plugin-id>/` for custom Tool Runtime tools.

## Safety Defaults

- Do not store plaintext provider keys, MCP tokens, or customer credentials in repo files. Use environment variables or credential references.
- Treat caller-supplied `metadata`, `tools[]`, and tool arguments as untrusted. Tool visibility and execution must still be closed by Tool Runtime policy.
- Use `local-unsafe` sandbox only for trusted local development. Prefer `opensandbox` or `external` for production command execution.
- When enabling `exec`, make the risk explicit and verify `agent.yaml` includes both requested tool and sandbox mode.

## Output Contract

When this skill is used, answer with:

- What was initialized, configured, debugged, or deployed.
- Exact files touched or inspected.
- The minimal commands to reproduce or verify.
- Any unresolved secrets, infra, or safety decisions the user must provide.
