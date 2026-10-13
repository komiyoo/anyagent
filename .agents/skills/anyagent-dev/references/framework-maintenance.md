# Framework maintenance

Update `.agents/skills/anyagent-dev/` in the same change when framework behavior that a business repo depends on changes:

- scaffold output, `anyagent init`, or `anyagent add`
- `.anyagent/anyagent.yaml` or `agent.yaml` fields, layering, or `${VAR}` interpolation
- skill discovery, MCP config, plugin loading, or tool names
- sandbox modes, credential backends, storage settings, or serve/dev flags
- the install source, repository URL, or release tag convention

Edit the one reference that owns the fact. `references/configuration.md` owns the file layout and layers. `references/workspace-quickstart.md` owns the generated tree. Do not copy the same rule into both.

Code to read before editing the skill:

- `packages/anyagent/src/anyagent/config/schema.py`
- `packages/anyagent/src/anyagent/config/defaults.py`
- `packages/anyagent/src/anyagent/config/env.py`
- `packages/anyagent/src/anyagent/config/loader.py`
- `packages/anyagent/src/anyagent/config/agents.py`
- `packages/anyagent/src/anyagent/scaffold/`

From the anyagent repo root:

```bash
python3 scripts/docs/check.py --root .
```

Ignore older docs that still mention `models.yaml`, `secrets.yaml`, or `*_env` when those sentences conflict with `packages/anyagent/src/anyagent/config/`.
