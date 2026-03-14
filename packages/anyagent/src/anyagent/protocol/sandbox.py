from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


SandboxMode = Literal["opensandbox", "external", "local-unsafe", "disabled"]
FileSystemPersistenceMode = Literal["ephemeral", "session_hot_cold"]


class ResourceLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cpu_cores: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, ge=1)
    disk_mb: int | None = Field(default=None, ge=1)
    output_max_bytes: int | None = Field(default=None, ge=0)


class NetworkSandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    allow_hosts: list[str] | None = None
    deny_hosts: list[str] | None = None


class FileSystemSandboxPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persistence_mode: FileSystemPersistenceMode = "ephemeral"
    workspace_root: str = Field(default="/workspace", min_length=1)
    hot_idle_ttl_s: int | None = Field(default=None, ge=0)
    cold_retention_s: int | None = Field(default=None, ge=1)
    max_snapshot_bytes: int | None = Field(default=None, ge=1)


class SandboxPolicy(BaseModel):
    """
    Sandbox policy SSOT used by AgentSpec and server runtime.

    v0 仅收敛最小字段：
    - mode：后端选择
    - network：网络策略占位
    - resource_limits：资源上限占位
    - ttl_seconds：会话级沙箱生命周期
    - filesystem：工作区持久化策略占位
    """

    model_config = ConfigDict(extra="ignore")

    mode: SandboxMode = "disabled"
    network: NetworkSandboxPolicy | None = None
    filesystem: FileSystemSandboxPolicy | None = None
    resource_limits: ResourceLimits | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_limits", "resources"),
    )
    ttl_seconds: int | None = Field(default=1800, ge=1)
