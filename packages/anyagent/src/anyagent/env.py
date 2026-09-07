"""Process environment helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping


def getenv(
    name: str,
    default: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Read exactly ``name`` from the process environment or ``environ``."""

    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is None:
        return default
    return value
