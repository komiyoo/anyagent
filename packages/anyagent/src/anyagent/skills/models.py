from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SkillScope = Literal["repo", "user", "system", "admin", "agent"]


class SkillFrontMatterMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    short_description: str | None = Field(default=None, alias="short-description")


class SkillFrontMatter(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    metadata: SkillFrontMatterMetadata | None = None


class SkillToolDependency(BaseModel):
    """
    v0 对齐 Codex 的 dependencies.tools[] 的最小形态（anyagent 只用其中一部分字段）。
    """

    model_config = ConfigDict(extra="allow")

    transport: str | None = None
    value: str | None = None
    type: str | None = None
    command: str | None = None
    url: str | None = None


class SkillAgentMetadata(BaseModel):
    """
    `agents/openai.yaml` 最小子集（解析失败必须 fail-open）。
    """

    model_config = ConfigDict(extra="allow")

    interface: dict[str, Any] | None = None
    dependencies_tools: list[SkillToolDependency] | None = Field(default=None, alias="dependencies.tools")
    policy: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None


class SkillPackage(BaseModel):
    """
    一个可加载 skill 的结构化表示（SDK 内部用）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    skill_dir: Path
    skill_md_path: Path
    scope: SkillScope

    frontmatter: SkillFrontMatter
    body_markdown: str
    agent_metadata: dict[str, Any] | None = None

    @property
    def stable_id(self) -> str:
        # v0：以 canonical path 作为稳定 key（更强治理/禁用粒度）
        return str(self.skill_md_path.resolve())
