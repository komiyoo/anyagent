from __future__ import annotations

from pydantic import BaseModel, Field


class PluginToolRef(BaseModel):
    """References one tool registered by a plugin."""

    name: str
    category: str
    kind: str | None = None
    description: str | None = None


class LoadedPluginCatalogItem(BaseModel):
    """Describes a loaded plugin and the tools it registered."""

    plugin_id: str
    description: str | None = None
    channels: list[str] = Field(default_factory=list)
    plugin_dir: str
    entrypoint: str
    tools: list[PluginToolRef] = Field(default_factory=list)
    cite: dict[str, str] = Field(default_factory=dict)
    docs: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class PluginLoadErrorItem(BaseModel):
    """Describes one plugin load failure without exposing config secrets."""

    plugin_dir: str
    reason: str


class PluginCatalogResponse(BaseModel):
    """Admin response for Core plugin discovery and traceability."""

    plugin_roots: list[str] = Field(default_factory=list)
    loaded: list[LoadedPluginCatalogItem] = Field(default_factory=list)
    errors: list[PluginLoadErrorItem] = Field(default_factory=list)
