# AnyAgent Studio

AnyAgent Studio is the no-code research and debug frontend bundled with the `anyagent` Python package. The frontend consumes the existing anyagent-compatible API surface instead of redefining agent protocol or runtime behavior.

Product direction: the shell is planned around two modes in the top-left brand area. Use mode focuses on running agents, session history, observability and evaluation; Build mode focuses on creating, configuring, debugging and iterating agents.

## What It Covers

- Select any workspace `agent_id`, including hidden spawn-only agents that are not externally exposed.
- Create a new exposed agent pack from Studio by writing `agent.yaml`, `AGENTS.md`, `mcp.json`, and a local skills directory through Core admin APIs
- Inspect the selected agent pack: `AGENTS.md` preview, `agent.yaml` summary, selected skills and MCP metadata
- Chat with the selected agent through the official OpenAI TypeScript SDK against `baseURL=<anyagent>/v1`
- Replay debug data through AnyAgent internal endpoints:
  - `/internal/events/list`
  - `/internal/prompt/bundle`
- Render stage events as a readable timeline for prompt assembly, tool calls, command calls, results, and completion states.
- Edit and save agent-pack source files through admin endpoints:
  - `AGENTS.md`
  - `agent.yaml`
  - `mcp.json`
- Import one agent-local skill by pasting validated `SKILL.md` content into the selected agent's `skills/<directory>/SKILL.md`.
- Install one skill from a `skills` CLI package through the Core admin endpoint, copied into the selected agent's local skills directory.
- Toggle which visible skills are default-selected for the agent without editing `agent.yaml` directly.
- Edit common `agent.yaml` controls without opening YAML: exposed state, sandbox mode, requested tools, and spawn-allow agent ids.
- Inspect the selected agent's effective tool catalog from Core, including tool names, descriptions, kind labels, and toolset version.
- Browse the registered tool pool and add tool names into the selected agent's requested tools form without memorizing tool ids.
- Create, list, and delete Credential Vault references for MCP/tool configuration without exposing saved secret values back to the browser.
- Build streamable HTTP / SSE / stdio MCP server drafts and save them back to the selected agent's `mcp.json`.
- Load existing `mcp.json` back into the form where possible; invalid JSON disables form save so the raw source editor remains the recovery path.
- Present the default workspace as a LangSmith-style operations console: persistent left navigation, project header quick actions, tracing table, compact client session, live stream panel, and Configure-only connection/admin forms.
- Current shell: a top-left Use/Build mode switch and collapsible sidebar. Use mode groups Home, Agents, Sessions, Observability, Evaluations, Prompts and Settings; Build mode groups Agents, Configure, Skills, MCP, Tools, Credentials, Debug, Files and Settings.
- Configure exposes browser-managed AnyAgent Server connection settings. `base_url`, API key, admin key, model, agent and session values default from `VITE_ANYAGENT_*`, can be tested before applying, and are saved in versioned browser local storage once applied.
- Use-mode Observability now has a v0 page backed by Core typed telemetry APIs: run history, summary, metrics, tool aggregation, normalized errors, timeline filtering, and trace drill-down. Local stream/stage events remain available through Home and Debug for live inspection.
- Build-mode Configure now exposes capsule-style enablement controls for skills, registered/requested tools, and MCP server drafts. Skill disablement is saved through `agent.yaml.skills.disabled_paths`; tool enablement is saved through `agent.yaml.tools.requested_tool_names`; MCP draft enablement is written to `mcp.json.enabled` and Core skips disabled MCP servers during connection, tool disclosure, and prompt ref assembly.
- Skill installation/import is channel-first in the UI. The installer defaults to `skills.sh`, keeps `registry` as a compatibility option, supports `github` repo/ref/path installs, and exposes `local_upload` for pasted `SKILL.md`. Imported and installed skills get `.anyagent-skill-source.json` sidecar metadata so later updates can target the original channel/ref.

Saving uses optimistic `sha256` checks and fixed file kinds from the server. Registry installs are intentionally routed through Core's restricted installer endpoint; the browser never executes shell commands directly.

## Run

The production path is served directly by Core:

```bash
anyagent serve --workspace ../../anyagent-apps/examples/demo-workspace --port 8787
open http://127.0.0.1:8787/
```

Use `--no-studio` when the API should start without the bundled frontend.

For frontend development, start an AnyAgent server first:

```bash
anyagent serve \
  --workspace ../../anyagent-apps/examples/demo-workspace \
  --cors-origin http://127.0.0.1:5177 \
  --port 8787
```

Then run Studio:

```bash
cd packages/anyagent/studio
npm install
VITE_ANYAGENT_BASE_URL=http://127.0.0.1:8787 \
VITE_ANYAGENT_API_KEY=anyagent-dev-key \
VITE_ANYAGENT_ADMIN_KEY=admin-key \
VITE_ANYAGENT_AGENT_ID=main \
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://127.0.0.1:5177/`.

## Build Check

```bash
cd packages/anyagent/studio
npm install
npm run build
```

## Deployment

Studio is a pure SPA and is deployed independently from the `anyagent` Python package (the built bundle is **not** committed to git or included in the wheel).

- `npm run build` writes the static bundle to `packages/anyagent/studio/dist/`.
- `base` defaults to `/` (standalone site root). To mount under a subpath, e.g. the server's `/studio/`, build with `VITE_BASE=/studio/ npm run build`.
- Deploy `dist/` to any static host (Cloudflare Pages, Nginx, S3, etc.). The SPA connects to the anyagent server at runtime via the server URL configured in Studio's Settings page; enable CORS on the server accordingly.

### Local development with `anyagent serve`

The server no longer bundles Studio. To serve a locally built bundle from `anyagent serve`, point it at the build output:

```bash
cd packages/anyagent/studio
VITE_BASE=/studio/ npm run build
ANYAGENT_STUDIO_DIR=packages/anyagent/studio/dist anyagent serve
```

Without `ANYAGENT_STUDIO_DIR`, or with `--no-studio`, the server mounts no Studio UI.

## Architecture Notes

- Client compatibility follows OpenAI Responses API through the official `openai` TypeScript SDK.
- AnyAgent-specific debug uses internal typed endpoints from Core/Agent API; the UI treats them as a superset rather than as a replacement for the OpenAI-compatible path.
- Agent-pack edits use admin-only Core endpoints; the browser never writes workspace files directly.
- The app source and bundled static assets now live in `anyagent`. Protocol shape, stage event schema, prompt bundle shape and agent catalog shape stay in AnyAgent Core Python modules.
- Frontend modules are split by responsibility: `anyagentClient.ts` is the typed server facade, `navigation.tsx` owns Use/Build page identity, `studioSettings.ts` owns browser-local connection settings, `studioUtils.ts` owns pure helpers, `hooks/` owns data-loading hooks, and `pages/` owns page-level UI such as `HomePage`, `AgentsPage`, `SessionsPage`, `ObservabilityPage`, `EvaluationsPage`, `PromptsPage`, `SettingsPage`, `CredentialsPage`, `DebugPage`, `SkillsPage`, `McpPage`, `ToolsPage`, `FilesPage`, and `ConfigurePage`.
- Page modules are loaded with `React.lazy` from `StudioApp`, so Use/Build surfaces become separate chunks instead of all shipping in the initial bundle.
- Current hooks include `useWorkspaceCatalog` for agent/skill catalog state, `useAgentFiles` for source file loading/saving/editor state, `useMcpDrafts` for `mcp.json` draft parsing and invalid JSON recovery state, `useToolCatalog` for effective/available tool catalogs, `useCredentials` for Credential Vault list/form/save/delete flows, `useSkillsManagement` for skill install/import, selection, disablement, and update flows, and `useObservability` for Use-mode telemetry queries, filtering, run selection, trace drill-down, and iteration suggestions.
- Configure-specific UI is split under `pages/configure/`: `ConnectionPanel` owns connection draft/apply/test controls, `CreateAgentPanel` owns new agent creation, `EffectiveConfigPanel` owns common `agent.yaml` controls and protocol summaries, and `ToolCatalogSection` is reused by Configure and the dedicated Tools page.
