from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "packages" / "anyagent" / "src" / "anyagent"

PUBLIC_SDK_MODULES = [
    SRC / "agent_api_client.py",
    SRC / "types" / "__init__.py",
]
SDK_LOCAL_EXAMPLE_MODULES = [
    SRC / "sdk_prompt_examples.py",
]

FORBIDDEN_SDK_IMPORT_PREFIXES = (
    "anyagent.cli",
    "anyagent.gateway",
    "anyagent.mcp",
    "anyagent.plugins",
    "anyagent.server",
    "anyagent.storage",
    "anyagent.tool_runtime",
)

KNOWN_SDK_BOUNDARY_DEBT_IMPORTS: set[str] = set()
KNOWN_SDK_LOCAL_EXAMPLE_IMPORTS: set[str] = set()

FORBIDDEN_PROTOCOL_IMPORT_PREFIXES = (
    "anyagent.agent_packs",
    "anyagent.agent_runtime",
    "anyagent.cli",
    "anyagent.gateway",
    "anyagent.mcp",
    "anyagent.plugins",
    "anyagent.server",
    "anyagent.skills",
    "anyagent.storage",
    "anyagent.tool_runtime",
)

KNOWN_PROTOCOL_BOUNDARY_DEBT_IMPORTS: set[str] = set()


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_public_python_sdk_does_not_import_server_runtime_modules() -> None:
    violations: list[str] = []
    for path in PUBLIC_SDK_MODULES:
        rel = path.relative_to(ROOT)
        for module in sorted(_imports(path)):
            if module in KNOWN_SDK_BOUNDARY_DEBT_IMPORTS:
                continue
            if _matches_prefix(module, FORBIDDEN_SDK_IMPORT_PREFIXES):
                violations.append(f"{rel}: {module}")

    assert violations == []


def test_python_sdk_local_helper_imports_stay_explicit_until_split() -> None:
    helper_imports = {
        module
        for path in PUBLIC_SDK_MODULES
        for module in _imports(path)
        if _matches_prefix(module, ("anyagent.agent_packs", "anyagent.agent_runtime", "anyagent.mcp", "anyagent.skills"))
    }

    assert helper_imports == KNOWN_SDK_BOUNDARY_DEBT_IMPORTS


def test_sdk_local_examples_are_the_only_sdk_runtime_helper_imports() -> None:
    helper_imports = {
        module
        for path in SDK_LOCAL_EXAMPLE_MODULES
        for module in _imports(path)
        if _matches_prefix(module, ("anyagent.agent_packs", "anyagent.agent_runtime", "anyagent.mcp", "anyagent.skills"))
    }

    assert helper_imports == KNOWN_SDK_LOCAL_EXAMPLE_IMPORTS


def test_protocol_modules_do_not_import_runtime_layers() -> None:
    violations: list[str] = []
    for path in sorted((SRC / "protocol").glob("*.py")):
        rel = path.relative_to(ROOT)
        for module in sorted(_imports(path)):
            if module in KNOWN_PROTOCOL_BOUNDARY_DEBT_IMPORTS:
                continue
            if _matches_prefix(module, FORBIDDEN_PROTOCOL_IMPORT_PREFIXES):
                violations.append(f"{rel}: {module}")

    assert violations == []


def test_protocol_runtime_import_debt_stays_explicit_until_split() -> None:
    runtime_imports = {
        module
        for path in sorted((SRC / "protocol").glob("*.py"))
        for module in _imports(path)
        if _matches_prefix(module, FORBIDDEN_PROTOCOL_IMPORT_PREFIXES)
    }

    assert runtime_imports == KNOWN_PROTOCOL_BOUNDARY_DEBT_IMPORTS
