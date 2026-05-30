from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "runtimes" / "rust-reference"


def test_rust_reference_runtime_declares_conformance_target() -> None:
    target = json.loads((TARGET / "conformance.json").read_text(encoding="utf-8"))

    assert target["runtime_id"] == "rust-reference"
    assert target["language"] == "rust"
    assert target["adr"] == "docs/architecture/decisions/second-runtime-rust-reference.md"
    assert "admin.credentials.capabilities" in target["supported_contracts"]
    assert "storage.replay" in target["partial_contracts"]
    assert "responses.api" in target["unsupported_contracts"]


def test_rust_reference_runtime_builds_when_cargo_is_available() -> None:
    if shutil.which("cargo") is None:
        raise AssertionError("cargo is required for the selected Rust second-runtime PoC")

    result = subprocess.run(
        ["cargo", "test", "--manifest-path", str(TARGET / "Cargo.toml")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
