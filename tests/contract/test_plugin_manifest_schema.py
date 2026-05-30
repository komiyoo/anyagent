from __future__ import annotations

import json
from pathlib import Path

from anyagent.plugins.schema_export import export_plugin_manifest_schema


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ARTIFACT = ROOT / "docs" / "schemas" / "plugin-manifest.schema.json"


def test_plugin_manifest_schema_export_is_deterministic_and_standalone() -> None:
    first = export_plugin_manifest_schema()
    second = export_plugin_manifest_schema()

    assert first == second
    assert first["manifest_version"] == "1"
    assert first["model"] == "anyagent.plugins.models.PluginManifest"
    assert "anyagent.protocol" not in first["model"]
    assert json.loads(json.dumps(first, sort_keys=True)) == first

    props = first["schema"]["properties"]
    assert props["manifest_version"]["const"] == "1"
    assert "hooks" in props
    hook_rule = {rule["id"]: rule for rule in first["semantic_rules"]}["plugin_manifest_hook_names_are_lifecycle_hooks"]
    assert hook_rule["allowed"] == ["on_agent_start", "on_agent_end"]


def test_plugin_manifest_schema_artifact_matches_export() -> None:
    expected = export_plugin_manifest_schema()
    actual = json.loads(SCHEMA_ARTIFACT.read_text(encoding="utf-8"))
    assert actual == expected
