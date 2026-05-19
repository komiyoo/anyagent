from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CredentialScope(BaseModel):
    """Declares where a credential is allowed to be used (v1: global/agent)."""

    level: Literal["global", "agent"] = Field(description="v1 only supports global/agent")
    agent_id: str | None = Field(default=None, description="Required when level=agent")

    @model_validator(mode="after")
    def _validate_agent_scope(self) -> "CredentialScope":
        if self.level == "agent" and not self.agent_id:
            raise ValueError("agent_id is required when scope.level=agent")
        if self.level != "agent" and self.agent_id is not None:
            raise ValueError("agent_id must be null unless scope.level=agent")
        return self


class AdminCredentialSetRequest(BaseModel):
    """Defines the write-only request body for Admin API credential set."""

    credential_id: str
    kind: str
    value: str
    scope: CredentialScope
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminCredentialRef(BaseModel):
    """Represents a credential reference without plaintext value."""

    credential_id: str
    kind: str
    scope: CredentialScope
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminCredentialListResponse(BaseModel):
    """Lists credential references (no plaintext values)."""

    credentials: list[AdminCredentialRef]


class CredentialBackendCapability(BaseModel):
    """Describes one credential backend mode without exposing secrets."""

    mode: str
    display_name: str
    kind: Literal["resolver", "admin_store"]
    status: Literal["stable", "preview", "planned"] = "stable"
    description: str
    supports_resolve: bool
    supports_set: bool
    supports_delete: bool
    supports_list_refs: bool
    read_only: bool
    default_for: list[str] = Field(default_factory=list)
    requires_extras: list[str] = Field(default_factory=list)
    requires_env: list[str] = Field(default_factory=list)
    source: str


class CredentialBackendCapabilityMatrix(BaseModel):
    """Lists Core credential backend modes and their operational capabilities."""

    resolver_modes: list[CredentialBackendCapability]
    admin_store_modes: list[CredentialBackendCapability]
    environment_variable: str = "MCP_CREDENTIAL_STORE_BACKEND"
    secret_value_returned: bool = False
