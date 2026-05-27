#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_local_package_path() -> None:
    src = _repo_root() / "packages" / "anyagent" / "src"
    sys.path.insert(0, str(src))


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export anyagent.protocol Pydantic schemas as a deterministic JSON bundle.")
    parser.add_argument(
        "--format",
        choices=["bundle", "openapi"],
        default="bundle",
        help="Export the schema bundle or a generated OpenAPI 3.1 document (default: bundle).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the schema bundle to this path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    _ensure_local_package_path()
    from anyagent.protocol.schema_export import export_openapi_document, export_protocol_schema_bundle

    payload = export_openapi_document() if args.format == "openapi" else export_protocol_schema_bundle()
    _write_json(args.out, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
