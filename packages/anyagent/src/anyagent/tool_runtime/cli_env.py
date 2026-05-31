from __future__ import annotations

import os
import re

from .cli_profile_spec import CliEnvironmentPolicy

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_ENV_PATTERNS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "AUTH",
    "KEY",
    "CREDENTIAL",
    "COOKIE",
)
CORE_ENV_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "PWD",
        "SHELL",
        "SHLVL",
        "TERM",
        "TMPDIR",
        "USER",
    }
)


def build_cli_env(policy: CliEnvironmentPolicy) -> dict[str, str]:
    if policy.inherit == "all":
        env = {key: value for key, value in os.environ.items() if _is_allowed_env_name(key)}
    elif policy.inherit == "core":
        env = {
            key: value
            for key, value in os.environ.items()
            if key in CORE_ENV_KEYS and _is_allowed_env_name(key)
        }
    else:
        env = {}

    if not policy.ignore_default_excludes:
        env = {key: value for key, value in env.items() if not _is_sensitive_env_key(key)}

    excluded = {item.strip() for item in policy.exclude if isinstance(item, str) and item.strip()}
    if excluded:
        env = {key: value for key, value in env.items() if key not in excluded}

    for key, value in policy.set.items():
        if _is_allowed_env_name(key):
            env[key] = value

    include_only = [item.strip() for item in policy.include_only if isinstance(item, str) and item.strip()]
    if include_only:
        include_set = set(include_only)
        env = {key: value for key, value in env.items() if key in include_set}

    return env


def _is_sensitive_env_key(key: str) -> bool:
    upper = key.upper()
    return any(pattern in upper for pattern in _SENSITIVE_ENV_PATTERNS)


def _is_allowed_env_name(key: str) -> bool:
    return bool(_ENV_NAME_RE.fullmatch(key))
