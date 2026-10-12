"""Deep merge and the workspace sensitive-field denylist."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


SENSITIVE_WORKSPACE_OVERRIDE_PATHS: tuple[tuple[str, ...], ...] = (
    ("sandbox", "mode"),
    ("storage",),
)


class ConfigMergeError(ValueError):
    """Raised when layered configuration cannot be merged safely."""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two JSON-like objects and return a new dict.

    Dict values merge. Lists and scalars from ``override`` replace the base.
    """

    merged = deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def validate_workspace_override_denylist(*, base: dict[str, Any], override: dict[str, Any], source: Path) -> None:
    """Reject workspace overrides for fields that must stay above workspace scope.

    ``base`` is the higher-trust document (system and user). Built-in defaults
    are not part of that document, so a workspace can still set storage when
    no higher layer did.
    """

    for path in SENSITIVE_WORKSPACE_OVERRIDE_PATHS:
        if _contains_path(base, path) and _contains_path(override, path):
            dotted = ".".join(path)
            raise ConfigMergeError(f"workspace config cannot override sensitive field {dotted}: {source}")


def _contains_path(value: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True
