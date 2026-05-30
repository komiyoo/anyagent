from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "protocol_schema_diff.py"


def _load_diff_module():
    spec = importlib.util.spec_from_file_location("protocol_schema_diff", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_schema_diff_detects_public_model_breaks() -> None:
    diff = _load_diff_module()
    old = {
        "models": {
            "Example": {
                "type": "object",
                "properties": {
                    "kept": {"type": ["string", "null"]},
                    "removed": {"type": "string"},
                    "mode": {"enum": ["a", "b"]},
                    "new_required": {"type": "string"},
                },
                "required": ["kept"],
            }
        },
        "type_adapters": {},
        "endpoints": [],
    }
    new = {
        "models": {
            "Example": {
                "type": "object",
                "properties": {
                    "kept": {"type": "string"},
                    "mode": {"enum": ["a"]},
                    "new_required": {"type": "string"},
                },
                "required": ["kept", "new_required"],
            }
        },
        "type_adapters": {},
        "endpoints": [],
    }

    issues = diff.diff_protocol_schema(old, new)

    assert [issue.code for issue in issues] == [
        "property_removed",
        "required_added",
        "type_narrowed",
        "enum_value_removed",
    ]


def test_protocol_schema_diff_detects_endpoint_contract_breaks() -> None:
    diff = _load_diff_module()
    old = {
        "models": {},
        "type_adapters": {},
        "endpoints": [
            {"operation": "responses.create", "method": "POST", "path": "/v1/responses", "response_model": "A"},
            {"operation": "responses.cancel", "method": "POST", "path": "/v1/responses/{id}/cancel"},
        ],
    }
    new = {
        "models": {},
        "type_adapters": {},
        "endpoints": [
            {"operation": "responses.create", "method": "PUT", "path": "/v1/responses", "response_model": "A"}
        ],
    }

    issues = diff.diff_protocol_schema(old, new)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("endpoint_removed", "endpoints.responses.cancel"),
        ("endpoint_contract_changed", "endpoints.responses.create.method"),
    ]
