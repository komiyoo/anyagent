#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DiffIssue:
    code: str
    path: str
    message: str

    def format(self) -> str:
        return f"{self.code}: {self.path}: {self.message}"


def load_bundle(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def diff_protocol_schema(old: dict[str, Any], new: dict[str, Any]) -> list[DiffIssue]:
    issues: list[DiffIssue] = []
    for section in ("models", "type_adapters"):
        old_schemas = _dict(old.get(section))
        new_schemas = _dict(new.get(section))
        for name in sorted(set(old_schemas) - set(new_schemas)):
            issues.append(DiffIssue("schema_removed", f"{section}.{name}", "schema no longer exists"))
        for name in sorted(set(old_schemas) & set(new_schemas)):
            issues.extend(_diff_schema(old_schemas[name], new_schemas[name], f"{section}.{name}"))
    issues.extend(_diff_endpoints(old.get("endpoints"), new.get("endpoints")))
    return issues


def _diff_schema(old: Any, new: Any, path: str) -> list[DiffIssue]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []

    issues: list[DiffIssue] = []
    old_types = _schema_types(old)
    new_types = _schema_types(new)
    if old_types and new_types and new_types < old_types:
        issues.append(
            DiffIssue(
                "type_narrowed",
                path,
                f"allowed types changed from {sorted(old_types)} to {sorted(new_types)}",
            )
        )

    old_enum = old.get("enum")
    new_enum = new.get("enum")
    if isinstance(old_enum, list) and isinstance(new_enum, list):
        removed = [value for value in old_enum if value not in new_enum]
        if removed:
            issues.append(DiffIssue("enum_value_removed", path, f"removed values: {removed!r}"))

    issues.extend(_diff_object_schema(old, new, path))

    if isinstance(old.get("items"), dict) and isinstance(new.get("items"), dict):
        issues.extend(_diff_schema(old["items"], new["items"], f"{path}.items"))

    for union_key in ("anyOf", "oneOf"):
        old_union = old.get(union_key)
        new_union = new.get(union_key)
        if isinstance(old_union, list) and isinstance(new_union, list) and len(old_union) == len(new_union):
            for idx, (old_branch, new_branch) in enumerate(zip(old_union, new_union, strict=True)):
                issues.extend(_diff_schema(old_branch, new_branch, f"{path}.{union_key}[{idx}]"))

    return issues


def _diff_object_schema(old: dict[str, Any], new: dict[str, Any], path: str) -> list[DiffIssue]:
    issues: list[DiffIssue] = []
    old_props = _dict(old.get("properties"))
    new_props = _dict(new.get("properties"))
    old_required = _string_set(old.get("required"))
    new_required = _string_set(new.get("required"))

    for prop in sorted(set(old_props) - set(new_props)):
        issues.append(DiffIssue("property_removed", f"{path}.{prop}", "public field no longer exists"))
    for prop in sorted(new_required - old_required):
        issues.append(DiffIssue("required_added", f"{path}.{prop}", "field became required"))
    for prop in sorted(set(old_props) & set(new_props)):
        issues.extend(_diff_schema(old_props[prop], new_props[prop], f"{path}.{prop}"))

    old_extra = old.get("additionalProperties")
    new_extra = new.get("additionalProperties")
    if old_extra is not False and new_extra is False:
        issues.append(DiffIssue("extra_forbidden", path, "additional properties became forbidden"))
    return issues


def _diff_endpoints(old_value: Any, new_value: Any) -> list[DiffIssue]:
    old_endpoints = _endpoints_by_operation(old_value)
    new_endpoints = _endpoints_by_operation(new_value)
    issues: list[DiffIssue] = []
    for operation in sorted(set(old_endpoints) - set(new_endpoints)):
        issues.append(DiffIssue("endpoint_removed", f"endpoints.{operation}", "operation no longer exists"))
    for operation in sorted(set(old_endpoints) & set(new_endpoints)):
        old_endpoint = old_endpoints[operation]
        new_endpoint = new_endpoints[operation]
        for key in ("method", "path", "request_model", "response_model"):
            if old_endpoint.get(key) != new_endpoint.get(key):
                issues.append(
                    DiffIssue(
                        "endpoint_contract_changed",
                        f"endpoints.{operation}.{key}",
                        f"changed from {old_endpoint.get(key)!r} to {new_endpoint.get(key)!r}",
                    )
                )
    return issues


def _endpoints_by_operation(value: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        return out
    for item in value:
        if not isinstance(item, dict):
            continue
        operation = item.get("operation")
        if isinstance(operation, str) and operation:
            out[operation] = item
    return out


def _schema_types(schema: dict[str, Any]) -> set[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    for union_key in ("anyOf", "oneOf"):
        union = schema.get(union_key)
        if isinstance(union, list):
            out: set[str] = set()
            for branch in union:
                if isinstance(branch, dict):
                    out.update(_schema_types(branch))
            return out
    enum = schema.get("enum")
    if isinstance(enum, list):
        return {_json_type_name(item) for item in enum}
    if "const" in schema:
        return {_json_type_name(schema.get("const"))}
    return set()


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect breaking changes between two anyagent protocol schema bundles.")
    parser.add_argument("--old", required=True, type=Path, help="Baseline protocol-schema.json.")
    parser.add_argument("--new", required=True, type=Path, help="Candidate protocol-schema.json.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable issues.")
    args = parser.parse_args(argv)

    issues = diff_protocol_schema(load_bundle(args.old), load_bundle(args.new))
    if args.json:
        print(json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2, sort_keys=True))
    elif issues:
        print("protocol_schema_diff: breaking changes detected", file=sys.stderr)
        for issue in issues:
            print(issue.format(), file=sys.stderr)
    else:
        print("protocol_schema_diff: OK")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
