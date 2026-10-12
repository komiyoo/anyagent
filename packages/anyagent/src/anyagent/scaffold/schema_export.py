"""JSON Schema export for the workspace config files."""

from __future__ import annotations

import json
from pathlib import Path

from anyagent.config.agents import AgentSpec
from anyagent.config.schema import WorkspaceConfig
from anyagent.mcp import MCPConfig
from anyagent.scaffold.files import ChangeLog

SCHEMA_DIR = Path(".anyagent") / "schema"
SCHEMA_FILES = (
    ("anyagent.yaml", "anyagent.schema.json"),
    ("agent.yaml", "agent.schema.json"),
    ("mcp.json", "mcp.schema.json"),
)


def export_config_schemas() -> dict[str, dict]:
    """Return JSON Schema documents for the three workspace config files."""

    return {
        "anyagent.yaml": WorkspaceConfig.model_json_schema(mode="validation", by_alias=True),
        "agent.yaml": AgentSpec.model_json_schema(mode="validation", by_alias=True),
        "mcp.json": MCPConfig.model_json_schema(mode="validation", by_alias=True),
    }


def write_schema_files(workspace: Path, log: ChangeLog, *, force: bool) -> None:
    """Write ``.anyagent/schema/*.schema.json`` from :func:`export_config_schemas`."""

    schemas = export_config_schemas()
    schema_dir = Path(workspace) / SCHEMA_DIR
    for key, filename in SCHEMA_FILES:
        text = json.dumps(schemas[key], indent=2, ensure_ascii=False) + "\n"
        log.write(schema_dir / filename, text, force=force)
