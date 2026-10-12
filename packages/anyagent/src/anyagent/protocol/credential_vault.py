from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CredentialScope(BaseModel):
    """Declares where a credential is allowed to be used."""

    level: Literal["global", "agent", "session"] = Field(description="Credential visibility level")
    agent_id: str | None = Field(default=None, description="Required when level=agent")
    session_key: str | None = Field(default=None, description="Required when level=session")

    @model_validator(mode="after")
    def _validate_scope(self) -> "CredentialScope":
        if self.level == "agent" and not self.agent_id:
            raise ValueError("agent_id is required when scope.level=agent")
        if self.level == "session" and not self.session_key:
            raise ValueError("session_key is required when scope.level=session")
        if self.level == "global" and (self.agent_id is not None or self.session_key is not None):
            raise ValueError("agent_id and session_key must be null when scope.level=global")
        if self.level == "agent" and self.session_key is not None:
            raise ValueError("session_key must be null unless scope.level=session")
        if self.level == "session" and self.agent_id is None:
            raise ValueError("agent_id is required when scope.level=session")
        return self


class AdminCredentialSetRequest(BaseModel):
    """Defines the write-only request body for Admin API credential set."""

    credential_id: str
    kind: str
    value: str
    scope: CredentialScope
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = Field(default=None, description="UTC expiration time; expired credentials are not resolved")
    rotate_before: datetime | None = Field(default=None, description="UTC time at which operators should rotate the credential")

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> "AdminCredentialSetRequest":
        if self.expires_at is not None and self.rotate_before is not None and self.rotate_before > self.expires_at:
            raise ValueError("rotate_before must be before or equal to expires_at")
        return self


class AdminCredentialRef(BaseModel):
    """Represents a credential reference without plaintext value."""

    credential_id: str
    kind: str
    scope: CredentialScope
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    rotate_before: datetime | None = None


class AdminCredentialListResponse(BaseModel):
    """Lists credential references (no plaintext values)."""

    credentials: list[AdminCredentialRef]


class AdminCredentialDeleteResponse(BaseModel):
    """Confirms deletion of one credential reference without exposing plaintext."""

    ok: bool
    deleted: bool
    credential_id: str


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
    environment_variable: str = "CREDENTIAL_BACKEND"
    secret_value_returned: bool = False
