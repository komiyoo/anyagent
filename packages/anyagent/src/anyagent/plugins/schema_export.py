from __future__ import annotations

from typing import Any

from .hooks import HOOK_NAMES
from .models import PluginManifest


PLUGIN_MANIFEST_SCHEMA_VERSION = "2026-05-30"


def export_plugin_manifest_schema() -> dict[str, Any]:
    """Export the standalone Plugin Manifest v1 contract schema.

    This deliberately lives under ``anyagent.plugins`` instead of
    ``anyagent.protocol``: plugins are a runtime extension surface, while the
    protocol bundle remains free of runtime/plugin imports.
    """

    return {
        "schema_version": PLUGIN_MANIFEST_SCHEMA_VERSION,
        "manifest_version": "1",
        "model": "anyagent.plugins.models.PluginManifest",
        "schema": PluginManifest.model_json_schema(mode="validation"),
        "semantic_rules": [
            {
                "id": "plugin_manifest_entrypoint_is_relative_python_attr",
                "fields": ["entrypoint"],
                "description": "Entrypoints use relative 'file.py:callable' paths under the plugin directory.",
                "pattern": "^[^:]+\\.py:[A-Za-z_][A-Za-z0-9_]*$",
            },
            {
                "id": "plugin_manifest_classpath_fields_use_module_attr",
                "fields": ["middlewares", "hooks"],
                "description": "Middleware and hook targets use 'module.path:callable' classpaths.",
                "pattern": "^[A-Za-z_][\\w.]*:[A-Za-z_]\\w*$",
            },
            {
                "id": "plugin_manifest_hook_names_are_lifecycle_hooks",
                "fields": ["hooks"],
                "description": "Only supported lifecycle hook names may be declared.",
                "allowed": list(HOOK_NAMES),
            },
        ],
    }
