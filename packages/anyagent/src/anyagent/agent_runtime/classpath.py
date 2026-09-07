from __future__ import annotations

import importlib
import re
from typing import Any

_CLASSPATH_RE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*):(?P<attr>[A-Za-z_]\w*)$")


def load_instance_from_classpath(
    classpath: str,
    *,
    label: str,
    required_method: str,
    error_cls: type[Exception],
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Import and instantiate ``"module.path:ClassName"`` and check it exposes ``required_method``.

    Shared by deployer-configured extension points (context providers, scripted
    reply providers). The classpath comes from trusted ``agent.yaml``; never feed
    model output or other untrusted text into this loader.
    """

    if not isinstance(classpath, str):
        raise error_cls(f"{label} classpath must be a string, got {type(classpath)!r}")
    match = _CLASSPATH_RE.match(classpath.strip())
    if match is None:
        raise error_cls(f"invalid {label} classpath (expected 'module.path:ClassName'): {classpath!r}")

    module_path = match.group("module")
    attr = match.group("attr")

    try:
        module = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001
        raise error_cls(f"cannot import {label} module {module_path!r}: {e}") from e

    try:
        target = getattr(module, attr)
    except AttributeError as e:
        raise error_cls(f"{label} attr {attr!r} not found in module {module_path!r}") from e

    if not isinstance(target, type):
        raise error_cls(f"{label} target {classpath!r} is not a class")

    try:
        instance = target(**(kwargs or {}))
    except Exception as e:  # noqa: BLE001
        raise error_cls(f"failed to instantiate {label} {classpath!r}: {e}") from e

    if not callable(getattr(instance, required_method, None)):
        raise error_cls(f"{label} {classpath!r} does not implement {required_method}(request)")
    return instance
