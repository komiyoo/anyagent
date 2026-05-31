from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from anyagent.protocol.sandbox import SandboxMode

from .models import ToolCredentialSpec

CliEnvironmentInheritance = Literal["core", "none", "all"]

_BANNED_COMMAND_SHELL_NAMES = (
    "bash",
    "env",
    "node",
    "perl",
    "pwsh",
    "python",
    "python3",
    "sh",
    "sudo",
    "zsh",
)
_BANNED_COMMAND_SHELL_FLAGS = ("-c", "-lc")


class CliEnvironmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inherit: CliEnvironmentInheritance = "core"
    ignore_default_excludes: bool = False
    exclude: list[str] = Field(default_factory=list)
    include_only: list[str] = Field(default_factory=list)
    set: dict[str, str] = Field(default_factory=dict)


class CliProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    cwd: str = "."
    sandbox: SandboxMode | None = None
    timeout_ms: int = Field(default=60_000, ge=1, le=600_000)
    allow_command_prefixes: list[str] = Field(default_factory=list)
    env: CliEnvironmentPolicy = Field(default_factory=CliEnvironmentPolicy)
    credentials: list[ToolCredentialSpec] = Field(default_factory=list)


BANNED_COMMAND_SHELLS = frozenset((*_BANNED_COMMAND_SHELL_NAMES, *_BANNED_COMMAND_SHELL_FLAGS))
