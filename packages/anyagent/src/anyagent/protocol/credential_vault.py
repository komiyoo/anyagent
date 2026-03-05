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

