"""Load the effective anyagent configuration from defaults, files, and CLI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from anyagent.config.defaults import builtin_defaults
from anyagent.config.env import getenv, interpolate, load_dotenv
from anyagent.config.merge import ConfigMergeError, deep_merge, validate_workspace_override_denylist
from anyagent.config.schema import (
    AlertsConfig,
    CredentialsConfig,
    ModelsConfig,
    ObservabilityConfig,
    PluginsConfig,
    SandboxConfig,
    ServerConfig,
    StorageConfig,
    ToolRuntimeConfig,
    WorkspaceConfig,
)


LayerName = Literal["default", "system", "user", "workspace", "cli"]

_CSV_PATHS = {
    ("server", "cors_origins"),
    ("plugins", "roots"),
    ("plugins", "builtin"),
    ("tool_runtime", "plugin_roots"),
}
_LEGACY_CREDENTIAL_ENV = {
    "MCP_CREDENTIAL_STORE_BACKEND": (
        "MCP_CREDENTIAL_STORE_BACKEND is no longer read. "
        "Set CREDENTIAL_BACKEND, and set credentials.writable: true "
        "(or CREDENTIAL_WRITABLE=true) instead of a -write suffix."
    ),
    "MCP_CREDENTIAL_STORE_FILE_ROOT": (
        "MCP_CREDENTIAL_STORE_FILE_ROOT is no longer read. Set CREDENTIAL_FILE_ROOT."
    ),
}
_SECRET_PARTS = (
    "api_key",
    "token",
    "secret",
    "password",
    "encryption_key",
    "client_secret",
    "access_key",
    "internal_key",
)
_URL_PASSWORD = re.compile(r"(://[^:/?#]+):([^@]+)@")


class ConfigLoadError(ValueError):
    """Raised when anyagent.yaml cannot be loaded or validated."""


@dataclass(frozen=True, slots=True)
class LeafSource:
    """Where one configured leaf came from."""

    layer: LayerName
    env: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    """Merged, interpolated configuration plus per-leaf provenance."""

    workspace_dir: Path
    config: WorkspaceConfig
    sources: dict[str, LeafSource]
    cli_overrides: dict[str, Any] | None = None

    @property
    def models(self) -> ModelsConfig:
        return self.config.models

    @property
    def server(self) -> ServerConfig:
        return self.config.server

    @property
    def storage(self) -> StorageConfig:
        return self.config.storage

    @property
    def credentials(self) -> CredentialsConfig:
        return self.config.credentials

    @property
    def sandbox(self) -> SandboxConfig:
        return self.config.sandbox

    @property
    def plugins(self) -> PluginsConfig:
        return self.config.plugins

    @property
    def observability(self) -> ObservabilityConfig:
        return self.config.observability

    @property
    def alerts(self) -> AlertsConfig:
        return self.config.alerts

    @property
    def tool_runtime(self) -> ToolRuntimeConfig:
        return self.config.tool_runtime

    def redacted_dump(self) -> dict[str, Any]:
        """Dump the document with secret values masked."""

        payload = self.config.model_dump(mode="json", by_alias=True)
        redacted = _redact(payload, "")
        assert isinstance(redacted, dict)
        return redacted

    def sources_dump(self) -> dict[str, dict[str, str | None]]:
        """Return per-leaf provenance as JSON-safe objects.

        Keys are dotted paths such as ``models.providers.openai.api_key``.
        ``env`` is the variable whose value was interpolated, when one was used.
        """

        return {
            path: {"layer": source.layer, "env": source.env}
            for path, source in sorted(self.sources.items())
        }


def load_effective_config(
    workspace_dir: str | Path,
    *,
    cli_overrides: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> EffectiveConfig:
    """Load defaults, system, user, workspace, then CLI overrides.

    Dotenv is applied once first. Interpolation runs after the merge.
    A workspace file cannot override sensitive fields that a system or user
    layer already set. CLI overrides may.
    """

    workspace = Path(workspace_dir).expanduser().resolve()
    if environ is None:
        load_dotenv(workspace)
        env = dict(os.environ)
    else:
        env = dict(environ)
    _reject_legacy_credential_env(env)

    system_path = _config_dir("SYSTEM_CONFIG_DIR", "/etc/anyagent", env) / "anyagent.yaml"
    user_path = _config_dir("USER_CONFIG_DIR", str(Path.home() / ".anyagent"), env) / "anyagent.yaml"
    workspace_path = workspace / ".anyagent" / "anyagent.yaml"

    layers: list[tuple[LayerName, Path, dict[str, Any]]] = [
        ("default", Path("<defaults>"), builtin_defaults()),
        ("system", system_path, _load_yaml_file(system_path)),
        ("user", user_path, _load_yaml_file(user_path)),
        ("workspace", workspace_path, _load_yaml_file(workspace_path)),
    ]
    higher = deep_merge(layers[1][2], layers[2][2])
    try:
        validate_workspace_override_denylist(base=higher, override=layers[3][2], source=workspace_path)
    except ConfigMergeError as exc:
        raise ConfigLoadError(str(exc)) from exc

    merged: dict[str, Any] = {}
    sources: dict[str, LeafSource] = {}
    for name, _path, payload in layers:
        merged = deep_merge(merged, payload)
        _assign_sources(sources, payload, name, "")
    if cli_overrides:
        override = cli_overrides
        merged = deep_merge(merged, override)
        _assign_sources(sources, override, "cli", "")

    expanded, used = interpolate(merged, env)
    if not isinstance(expanded, dict):
        raise ConfigLoadError(f"invalid anyagent.yaml: {workspace_path}: document must be an object")
    for path, env_name in used.items():
        dotted = ".".join(path)
        current = sources.get(dotted)
        if current is not None:
            sources[dotted] = LeafSource(current.layer, env_name)
    _coerce_csv_lists(expanded, ())
    _coerce_paths(expanded, ())
    _scrub_empty_strings(expanded, "", sources)
    try:
        document = WorkspaceConfig.model_validate(expanded)
    except ValidationError as exc:
        blame = _blame_path(layers, exc)
        raise ConfigLoadError(_format_validation(blame, exc)) from exc
    return EffectiveConfig(
        workspace_dir=workspace,
        config=document,
        sources=sources,
        cli_overrides=dict(cli_overrides) if cli_overrides else None,
    )


def _config_dir(env_name: str, default: str, env: dict[str, str]) -> Path:
    raw = getenv(env_name, default, environ=env) or default
    return Path(raw).expanduser()


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ConfigLoadError(f"invalid anyagent.yaml: {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigLoadError(f"invalid anyagent.yaml: {path}: document must be an object")
    return loaded


def _assign_sources(sources: dict[str, LeafSource], node: Any, layer: LayerName, prefix: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                sources.pop(child, None)
                _assign_sources(sources, value, layer, child)
            else:
                _drop_prefix(sources, child)
                sources[child] = LeafSource(layer)
        return
    if prefix:
        _drop_prefix(sources, prefix)
        sources[prefix] = LeafSource(layer)


def _drop_prefix(sources: dict[str, LeafSource], prefix: str) -> None:
    for key in [item for item in sources if item == prefix or item.startswith(prefix + ".")]:
        del sources[key]


_PATH_FIELDS = {
    ("server", "sandbox_root"),
    ("server", "studio_dir"),
    ("storage", "rollout_root_dir"),
    ("tool_runtime", "sandbox_root_dir"),
    ("tool_runtime", "workspace_event_root_dir"),
    ("credentials", "file", "root"),
    ("sandbox", "metadata_root_dir"),
    ("sandbox", "snapshot_root_dir"),
}
_PATH_LIST_FIELDS = {
    ("plugins", "roots"),
    ("tool_runtime", "plugin_roots"),
    ("server", "cors_origins"),
}


def _coerce_paths(node: Any, path: tuple[str, ...]) -> None:
    """Turn Path overrides into strings before schema validation."""

    if isinstance(node, dict):
        for key, value in list(node.items()):
            child = path + (str(key),)
            if child in _PATH_FIELDS and isinstance(value, Path):
                node[key] = str(value)
            elif child in _PATH_LIST_FIELDS and isinstance(value, (list, tuple)):
                node[key] = [str(item) if isinstance(item, Path) else item for item in value]
            else:
                _coerce_paths(value, child)


def _coerce_csv_lists(node: Any, path: tuple[str, ...]) -> None:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            child = path + (str(key),)
            if child in _CSV_PATHS and isinstance(value, str):
                node[key] = [item.strip() for item in value.split(",") if item.strip()]
            else:
                _coerce_csv_lists(value, child)


def _scrub_empty_strings(node: Any, prefix: str, sources: dict[str, LeafSource]) -> None:
    if not isinstance(node, dict):
        return
    for key in list(node.keys()):
        child = f"{prefix}.{key}" if prefix else str(key)
        value = node[key]
        if value == "":
            del node[key]
            sources.pop(child, None)
            continue
        _scrub_empty_strings(value, child, sources)


def _reject_legacy_credential_env(env: dict[str, str]) -> None:
    for name, message in _LEGACY_CREDENTIAL_ENV.items():
        raw = env.get(name)
        if isinstance(raw, str) and raw.strip():
            raise ConfigLoadError(message)


def _blame_path(layers: list[tuple[LayerName, Path, dict[str, Any]]], exc: ValidationError) -> Path:
    for err in exc.errors():
        loc = tuple(str(item) for item in err.get("loc", ()))
        for _name, path, payload in reversed(layers):
            if loc and _has_loc(payload, loc):
                return path
    return layers[-1][1]


def _has_loc(node: Any, loc: tuple[str, ...]) -> bool:
    current = node
    for key in loc:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _format_validation(path: Path, exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err.get("loc", ()))
        message = str(err.get("msg") or "invalid")
        parts.append(f"{loc}: {message}" if loc else message)
    detail = "; ".join(parts) or str(exc)
    return f"invalid anyagent.yaml: {path}: {detail}"


def _redact(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {str(item_key): _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str) and value:
        lowered = key.lower()
        if any(part in lowered for part in _SECRET_PARTS):
            return "***"
        if "dsn" in lowered or _URL_PASSWORD.search(value):
            return _URL_PASSWORD.sub(r"\1:***@", value)
    return value
