from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PromptVersionSourceKind = Literal["workspace_agents_md", "agent_agents_md", "agent_yaml", "mcp_json"]


class PromptVersionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PromptVersionSourceKind
    path: str
    sha256: str
    text: str


class PromptVersionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    agent_id: str
    label: str | None = None
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    sources: list[PromptVersionSource] = Field(default_factory=list)
    combined_sha256: str


class PromptVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    label: str | None = None


class PromptVersionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    versions: list[PromptVersionSnapshot] = Field(default_factory=list)


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: PromptVersionSnapshot


class PromptVersionDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    from_version_id: str
    to_version_id: str
    diff: str


class PromptVersionRestoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    version_id: str
    restored_paths: list[str] = Field(default_factory=list)
