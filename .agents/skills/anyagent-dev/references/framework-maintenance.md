# Framework Maintenance

Use this reference when anyagent itself changes and downstream developer guidance may drift.

## Update Trigger

Whenever a framework change touches any item below, inspect and update `.agents/skills/anyagent-dev/` in the same change:

- CLI commands, flags, default keys, or generated workspace layout.
- `.anyagent/` config schema, merge layers, hot/cold reload boundaries, or agent routing.
- `AGENTS.md` prompt injection semantics.
- Skill discovery, selection, metadata, or tool dependency semantics.
- MCP config or credential reference shape.
- Tool Runtime manifest/execute contract, tool naming, plugin loading, or deferred tool search.
- Sandbox modes or security defaults.
- Storage, replay, observability, Studio, or SDK debugging helpers.
- Deployment topology for built-in, distributed, or production runtime.

## Maintenance Checklist

1. Locate truth:
   ```bash
   rg -n "init|config show|doctor|agent list|tool-runtime serve|agent-api serve|sandbox|skills|mcp|credential" README.md docs packages/anyagent/src/anyagent
   ```
2. Update the smallest skill surface:
   - `SKILL.md` for high-level workflow or trigger changes.
   - `references/workspace-quickstart.md` for initialization/layout changes.
   - `references/configuration.md` for config schemas and runtime semantics.
   - `references/debugging.md` for troubleshooting and SDK helper changes.
   - `references/deployment.md` for serving, storage, sandbox, and production topology changes.
3. Keep examples executable and secrets redacted.
4. Validate:
   ```bash
   python3 /Users/ticoag/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/anyagent-dev
   python3 scripts/docs/check.py --root .
   anyagent doctor --workspace .
   ```
5. If this repo's generated demo workspace behavior changed, also check `docs/guides/getting-started.md` and `packages/anyagent/src/anyagent/cli/` examples.

## Style

- Keep `SKILL.md` concise and route details into references.
- Do not duplicate long design docs. Link to repo truth and summarize only operational decisions a business-repo agent needs.
- Prefer commands that work from a business repo root.
- Mention file paths that should be inspected before editing.
