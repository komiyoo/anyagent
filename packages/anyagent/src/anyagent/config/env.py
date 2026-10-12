"""One dotenv loader and one ${VAR} interpolator for anyagent configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INLINE_COMMENT = re.compile(r"\s+#")
_ESCAPE = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


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


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv text.

    Supports an ``export `` prefix, single and double quotes, and inline
    comments after unquoted values. Quoted values keep their contents and
    ignore a trailing comment outside the quotes.
    """

    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not _IDENT.fullmatch(key):
            continue
        parsed[key] = _parse_dotenv_value(rest.strip())
    return parsed


def load_dotenv(
    workspace_dir: str | Path,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Load ``.env`` then ``.env.local`` without overriding existing keys.

    ``.env.local`` wins over ``.env``. Keys already present in the target
    environment are left untouched. Returns the keys this call wrote.
    """

    target: MutableMapping[str, str] = os.environ if environ is None else environ
    workspace = Path(workspace_dir).expanduser()
    parsed: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = workspace / name
        if not path.is_file():
            continue
        parsed.update(parse_dotenv(path.read_text(encoding="utf-8")))
    applied: dict[str, str] = {}
    for key, value in parsed.items():
        if key not in target:
            target[key] = value
            applied[key] = value
    return applied


def interpolate(value: Any, environ: Mapping[str, str] | None = None) -> tuple[Any, dict[tuple[str, ...], str]]:
    """Expand ``${VAR}`` and ``${VAR:-default}`` in strings, lists, and dicts.

    A missing variable with no default becomes an empty string. Nested
    defaults are expanded. The returned map records, for each path that
    consumed an environment variable, the variable whose value was used.
    ``:-`` follows bash: an unset or empty value selects the default.
    """

    source = os.environ if environ is None else environ
    used: dict[tuple[str, ...], str] = {}

    def walk(node: Any, path: tuple[str, ...]) -> Any:
        if isinstance(node, str):
            expanded, env_name = interpolate_string(node, source)
            if env_name:
                used[path] = env_name
            return expanded
        if isinstance(node, list):
            return [walk(item, path + (str(index),)) for index, item in enumerate(node)]
        if isinstance(node, dict):
            return {str(key): walk(item, path + (str(key),)) for key, item in node.items()}
        return node

    return walk(value, ()), used


def interpolate_string(text: str, environ: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """Expand placeholders in one string. Returns the text and the env var used."""

    source = os.environ if environ is None else environ
    if "${" not in text:
        return text, None
    parts: list[str] = []
    env_used: str | None = None
    index = 0
    while index < len(text):
        if text.startswith("${", index):
            end = _closing_brace(text, index + 2)
            if end < 0:
                parts.append(text[index])
                index += 1
                continue
            replacement, env_name = _expand_placeholder(text[index + 2 : end], source)
            if env_name and env_used is None:
                env_used = env_name
            parts.append(replacement)
            index = end + 1
            continue
        parts.append(text[index])
        index += 1
    return "".join(parts), env_used


def _parse_dotenv_value(value: str) -> str:
    if not value:
        return ""
    if value[0] == '"':
        chars: list[str] = []
        index = 1
        while index < len(value):
            char = value[index]
            if char == "\\" and index + 1 < len(value):
                chars.append(_ESCAPE.get(value[index + 1], value[index + 1]))
                index += 2
                continue
            if char == '"':
                return "".join(chars)
            chars.append(char)
            index += 1
        return "".join(chars)
    if value[0] == "'":
        end = value.find("'", 1)
        if end < 0:
            return value[1:]
        return value[1:end]
    comment = _INLINE_COMMENT.search(value)
    if comment:
        value = value[: comment.start()]
    return value.strip()


def _closing_brace(text: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(text):
        if text.startswith("${", index):
            depth += 1
            index += 2
            continue
        if text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _expand_placeholder(inner: str, environ: Mapping[str, str]) -> tuple[str, str | None]:
    name, default, has_default = _split_default(inner)
    if not _IDENT.fullmatch(name):
        return "${" + inner + "}", None
    if has_default:
        current = environ.get(name)
        if current:
            return current, name
        return interpolate_string(default, environ)
    current = environ.get(name)
    if current is None:
        return "", None
    return current, name


def _split_default(inner: str) -> tuple[str, str, bool]:
    depth = 0
    index = 0
    while index < len(inner):
        if inner.startswith("${", index):
            depth += 1
            index += 2
            continue
        if inner[index] == "}" and depth:
            depth -= 1
            index += 1
            continue
        if depth == 0 and inner.startswith(":-", index):
            return inner[:index], inner[index + 2 :], True
        index += 1
    return inner, "", False
