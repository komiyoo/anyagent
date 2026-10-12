"""Public scaffold options and results."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ComponentKind = Literal["agent", "skill", "tool", "mcp", "plugin"]


class ScaffoldError(ValueError):
    """Raised when scaffold input is invalid or a generated file would be unsafe."""


class InitOptions(BaseModel):
    """Options for ``init_workspace``.

    ``tools`` and the ``with_*`` flags are added to the primary agent on top of
    the selected template. ``model`` is written as ``provider:model`` only when
    it differs from the built-in default.
    """

    model_config = ConfigDict(extra="forbid")

    workspace: Path
    agent_id: str = "main"
    template: str = "basic"
    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    tools: list[str] = Field(default_factory=list)
    with_exec: bool = False
    with_web_fetch: bool = False
    sandbox_mode: str | None = None
    with_example_skill: bool = False
    force: bool = False


class AddOptions(BaseModel):
    """Options for ``add_component``."""

    model_config = ConfigDict(extra="forbid")

    workspace: Path
    kind: ComponentKind
    name: str
    agent_id: str = "main"
    force: bool = False
    extra: dict[str, str] = Field(default_factory=dict)


class ScaffoldResult(BaseModel):
    """Files created, left untouched, or edited by ``add_component``."""

    model_config = ConfigDict(extra="forbid")

    created: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
