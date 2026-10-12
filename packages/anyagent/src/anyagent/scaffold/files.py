"""Template rendering and comment-preserving YAML/JSON edits.

YAML round-trips through PyYAML (``sort_keys=False``). Leading comment lines,
including the yaml-language-server schema directive, are kept. Comments inside
the document are not preserved; ruamel.yaml is not a dependency.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable, Mapping
from pathlib import Path
from string import Template
from typing import Any

import yaml

from anyagent.config.models import get_provider_spec, is_registered_provider_name, resolve_provider_kind
from anyagent.config.models_kinds import ModelProviderKind
from anyagent.scaffold.models import ScaffoldError
from anyagent.tool_runtime.registry import RESERVED_NAMES, TOOL_NAME_RE, ToolRegistry

TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
PLUGIN_ROOT = "plugins"
TEMPLATES = ("basic", "coding-agent", "research-agent", "multi-agent-team")
SANDBOX_MODES = ("opensandbox", "external", "local-unsafe", "disabled")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SCHEMA_LINE_RE = re.compile(r"^#\s*yaml-language-server:\s*\$schema=\S+\s*$")
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|token|authorization|credential_value|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|Bearer\s+\S|-----BEGIN |eyJ[A-Za-z0-9_-]{10,}\.)"
)
_URL_USERINFO_RE = re.compile(r"://[^/\s:]+:[^/\s@]+@")
_BUILTIN_TOOL_PREFIXES = ("core.", "sandbox.", "admin.")
_BASE_URL_ENV = {
    "openai": "OPENAI_BASE_URL",
    "openai_chat": "OPENAI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
}
_EXTRA_KEYS = {
    "agent": {"exposed"},
    "skill": set(),
    "tool": set(),
    "plugin": set(),
    "mcp": {"url", "command", "args", "credential_id"},
}

ANYAGENT_SCHEMA_LINE = "# yaml-language-server: $schema=./schema/anyagent.schema.json"
AGENT_SCHEMA_LINE = "# yaml-language-server: $schema=../../schema/agent.schema.json"
MCP_SCHEMA_REF = "../../schema/mcp.schema.json"


def read_template(relative: str) -> str:
    path = TEMPLATE_ROOT / relative
    if not path.is_file():
        raise ScaffoldError(f"missing scaffold template: {relative}")
    return path.read_text(encoding="utf-8")


def render_template(relative: str, **values: str) -> str:
    try:
        return Template(read_template(relative)).substitute(values)
    except KeyError as exc:
        raise ScaffoldError(f"scaffold template {relative} is missing {exc}") from exc


def validate_agent_id(agent_id: str) -> str:
    value = agent_id.strip()
    if not _NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise ScaffoldError("agent_id must match [A-Za-z0-9_.-]{1,64}")
    return value


def validate_component_name(name: str, *, kind: str) -> str:
    value = name.strip()
    if not _NAME_RE.fullmatch(value):
        raise ScaffoldError(f"{kind} name must match [A-Za-z0-9_.-]{1,64}")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ScaffoldError(f"{kind} name is not a safe path segment")
    return value


def validate_template_name(template: str) -> str:
    value = template.strip()
    if value not in TEMPLATES:
        allowed = ", ".join(TEMPLATES)
        raise ScaffoldError(f"unknown template {value!r}; expected one of: {allowed}")
    return value


def validate_sandbox_mode(mode: str) -> str:
    value = mode.strip()
    if value not in SANDBOX_MODES:
        allowed = ", ".join(SANDBOX_MODES)
        raise ScaffoldError(f"sandbox_mode must be one of: {allowed}")
    return value


def reject_plaintext_secrets(extra: Mapping[str, str]) -> None:
    """Refuse extra fields that would write a credential value into the workspace."""

    for key, value in extra.items():
        if not isinstance(value, str):
            raise ScaffoldError(f"extra.{key} must be a string")
        if key != "credential_id" and _SECRET_KEY_RE.search(key):
            raise ScaffoldError(f"refusing to write secret field extra.{key}; use credential_id")
        if _SECRET_VALUE_RE.search(value) or _URL_USERINFO_RE.search(value):
            raise ScaffoldError(f"refusing to write a plaintext secret in extra.{key}")


def reject_unknown_extra(kind: str, extra: Mapping[str, str]) -> None:
    unknown = sorted(set(extra) - _EXTRA_KEYS[kind])
    if unknown:
        allowed = ", ".join(sorted(_EXTRA_KEYS[kind])) or "(none)"
        raise ScaffoldError(f"unsupported extra keys for {kind}: {', '.join(unknown)}; allowed: {allowed}")


def canonical_provider(provider: str) -> tuple[str, ModelProviderKind, bool]:
    """Return ``(config key, kind, registered)`` for an init provider name."""

    raw = provider.strip()
    if not raw or not _NAME_RE.fullmatch(raw):
        raise ScaffoldError("provider must match [A-Za-z0-9_.-]{1,64}")
    if is_registered_provider_name(raw):
        kind = resolve_provider_kind(raw)
        return kind, kind, True
    return raw, "openai", False


def render_env_example(*, provider: str) -> str:
    key, kind, _registered = canonical_provider(provider)
    spec = get_provider_spec(kind)
    lines = [f"{name}=" for name in spec.default_api_key_envs]
    url_var = _BASE_URL_ENV.get(kind)
    optional: list[str] = []
    if url_var:
        optional.append(f"# {url_var}={spec.default_base_url}")
    if kind == "anthropic":
        optional.append("# ANTHROPIC_VERSION=")
    assignments = "\n".join(lines)
    if optional:
        assignments = assignments + "\n" + "\n".join(optional)
    return render_template(
        "workspace/env.example.tmpl",
        provider=key,
        kind=kind,
        assignments=assignments,
    )


def resolve_tool_identity(name: str) -> tuple[str, str, str]:
    """Return ``(plugin_id, tool_name, category)`` for ``anyagent add tool``.

    A bare name such as ``echo`` becomes the tool ``app.echo``. Names that are
    already public tool ids (``app.*`` or ``<channel>.*``) are kept. Built-in
    tool names are rejected.
    """

    plugin_id = validate_component_name(name, kind="tool")
    if plugin_id in RESERVED_NAMES or plugin_id.startswith(_BUILTIN_TOOL_PREFIXES):
        raise ScaffoldError(
            f"{plugin_id} is a built-in tool. Add it to tools.requested_tool_names in agent.yaml "
            "instead of generating a plugin."
        )
    if _is_public_tool_name(plugin_id):
        tool_name = plugin_id
    else:
        tool_name = f"app.{plugin_id.lower()}"
        if not _is_public_tool_name(tool_name):
            raise ScaffoldError(f"cannot derive a public tool name from {plugin_id}")
    category = ToolRegistry._expected_category_for_name(tool_name)
    if category is None:
        raise ScaffoldError(f"cannot infer a tool category for {tool_name}")
    return plugin_id, tool_name, category


def _is_public_tool_name(name: str) -> bool:
    if name in RESERVED_NAMES or name.startswith(_BUILTIN_TOOL_PREFIXES):
        return False
    if not TOOL_NAME_RE.fullmatch(name):
        return False
    if name.startswith(".") or name.endswith(".") or ".." in name:
        return False
    return ToolRegistry._expected_category_for_name(name) is not None


def parse_exposed(value: str) -> bool:
    token = value.strip().lower()
    if token in {"1", "true", "yes"}:
        return True
    if token in {"0", "false", "no"}:
        return False
    raise ScaffoldError("extra.exposed must be true or false")


def parse_command_args(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScaffoldError(f"mcp args is not valid JSON: {exc}") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ScaffoldError("mcp args JSON must be an array of strings")
        return parsed
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise ScaffoldError(f"mcp args could not be parsed: {exc}") from exc


def ensure_list_item(document: dict[str, Any], path: tuple[str, ...], item: str) -> bool:
    """Append ``item`` at ``path`` if it is absent. Return whether the document changed."""

    if not path:
        raise ScaffoldError("list path is empty")
    current = document
    for key in path[:-1]:
        node = current.get(key)
        if node is None:
            node = {}
            current[key] = node
        if not isinstance(node, dict):
            raise ScaffoldError(f"{'.'.join(path)} cannot be updated because {key} is not a mapping")
        current = node
    leaf = path[-1]
    values = current.get(leaf)
    if values is None:
        current[leaf] = [item]
        return True
    if isinstance(values, str):
        items = [part.strip() for part in values.split(",") if part.strip()]
        if item in items:
            return False
        items.append(item)
        current[leaf] = items
        return True
    if not isinstance(values, list):
        raise ScaffoldError(f"{'.'.join(path)} must be a list")
    if item in values:
        return False
    values.append(item)
    return True


def load_yaml_with_header(text: str) -> tuple[list[str], dict[str, Any]]:
    lines = text.splitlines()
    header: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "" or stripped.startswith("#"):
            header.append(lines[index])
            index += 1
            continue
        break
    try:
        loaded = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise ScaffoldError(f"invalid YAML: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ScaffoldError("YAML document must be a mapping")
    return header, loaded


def dump_yaml_with_header(header: list[str], data: dict[str, Any], schema_line: str) -> str:
    rendered_header = _ensure_schema(list(header), schema_line)
    parts: list[str] = []
    if rendered_header:
        parts.append("\n".join(rendered_header).rstrip())
    if data:
        dumped = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1_000_000,
        ).rstrip("\n")
        parts.append(dumped)
    return "\n".join(parts) + "\n"


def _ensure_schema(header: list[str], schema_line: str) -> list[str]:
    if any(_SCHEMA_LINE_RE.match(line.strip()) for line in header):
        return header
    return [schema_line, *header]


def update_yaml(
    path: Path,
    schema_line: str,
    mutate: Callable[[dict[str, Any]], None],
    log: ChangeLog,
) -> None:
    existed = path.is_file()
    if existed:
        header, data = load_yaml_with_header(path.read_text(encoding="utf-8"))
    else:
        header, data = [], {}
    mutate(data)
    log.rewrite(path, dump_yaml_with_header(header, data, schema_line))


def update_json(path: Path, mutate: Callable[[dict[str, Any]], None], log: ChangeLog) -> None:
    existed = path.is_file()
    if existed:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScaffoldError(f"invalid JSON: {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ScaffoldError(f"JSON document must be an object: {path}")
        data = loaded
    else:
        data = {}
    mutate(data)
    log.rewrite(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def agent_document(
    *,
    exposed: bool = True,
    tools: list[str] | None = None,
    skills: list[str] | None = None,
    sandbox_mode: str | None = None,
    spawn: list[str] | None = None,
) -> dict[str, Any]:
    """Agent fields that differ from ``AgentSpec`` defaults."""

    document: dict[str, Any] = {}
    if exposed is False:
        document["exposed"] = False
    if tools:
        document["tools"] = {"requested_tool_names": list(tools)}
    if skills:
        document["skills"] = {"default_selected": list(skills)}
    if sandbox_mode and sandbox_mode != "disabled":
        document["sandbox"] = {"mode": sandbox_mode}
    if spawn:
        document["multiagent"] = {"spawn_allow_agent_ids": list(spawn)}
    return document


def merge_tools(
    base: list[str],
    extra: list[str],
    *,
    with_web_fetch: bool,
    with_exec: bool,
) -> list[str]:
    merged: list[str] = []
    for name in [*base, *extra]:
        value = name.strip()
        if value and value not in merged:
            merged.append(value)
    if with_web_fetch and "core.web_fetch" not in merged:
        merged.append("core.web_fetch")
    if with_exec and "exec" not in merged:
        merged.append("exec")
    return merged


def effective_sandbox(template_mode: str, *, override: str | None, with_exec: bool) -> str:
    if override is not None and override.strip():
        return validate_sandbox_mode(override)
    if with_exec and template_mode == "disabled":
        return "local-unsafe"
    return template_mode


def next_steps(workspace: Path) -> list[str]:
    quoted = shlex.quote(str(workspace))
    return [
        f"anyagent doctor --workspace {quoted}",
        f"anyagent serve --workspace {quoted}",
    ]


class ChangeLog:
    """Record created, skipped, and updated files.

    ``overwrite_as="created"`` matches ``WorkspaceInitResult``, which has no
    updated list: a forced rewrite is reported as created.
    """

    def __init__(self, *, overwrite_as: str = "updated") -> None:
        if overwrite_as not in {"created", "updated"}:
            raise ScaffoldError(f"unsupported overwrite bucket: {overwrite_as}")
        self.overwrite_as = overwrite_as
        self.created: list[str] = []
        self.skipped: list[str] = []
        self.updated: list[str] = []

    def write(self, path: Path, text: str, *, force: bool) -> None:
        target = Path(path).resolve()
        rendered = _normalize(text)
        if target.is_file():
            current = target.read_text(encoding="utf-8")
            if current == rendered or not force:
                self.skipped.append(str(target))
                return
            target.write_text(rendered, encoding="utf-8")
            self._bucket(self.overwrite_as).append(str(target))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        self.created.append(str(target))

    def rewrite(self, path: Path, text: str) -> None:
        """Write ``path`` when its text changed. Existing files count as updated."""

        target = Path(path).resolve()
        rendered = _normalize(text)
        existed = target.is_file()
        if existed and target.read_text(encoding="utf-8") == rendered:
            self.skipped.append(str(target))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        if existed:
            self.updated.append(str(target))
        else:
            self.created.append(str(target))

    def _bucket(self, name: str) -> list[str]:
        if name == "created":
            return self.created
        return self.updated


def _normalize(text: str) -> str:
    if text == "" or text.endswith("\n"):
        return text
    return text + "\n"
