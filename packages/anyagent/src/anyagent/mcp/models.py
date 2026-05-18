from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MCPServerTransport(str, Enum):
    """Defines supported MCP client transports."""

    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"
    STDIO = "stdio"


class MCPServerAuthConfig(BaseModel):
    """Describes how to resolve and inject credentials for one MCP server."""

    model_config = ConfigDict(extra="ignore")

    credential_id: str
    ref_kind: str = "bearer_token"
    injection: str = "header:Authorization"
    format: str = "Bearer {value}"


class MCPToolFilterConfig(BaseModel):
    """Defines optional allow/deny filters for MCP tool names."""

    model_config = ConfigDict(extra="ignore")

    allowed_tool_names: list[str] | None = None
    blocked_tool_names: list[str] | None = None


class MCPServerConfig(BaseModel):
    """Defines one MCP server configuration entry."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    # transport 自动推断：有 url → streamable_http/sse，有 command → stdio
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    transport: MCPServerTransport | None = None
    headers: dict[str, str] | None = None
    auth: MCPServerAuthConfig | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    idle_timeout_seconds: float = Field(default=300.0, ge=0)
    tool_filter: MCPToolFilterConfig | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> "MCPServerConfig":
        has_url = isinstance(self.url, str) and bool(self.url.strip())
        has_command = isinstance(self.command, str) and bool(self.command.strip())
        if has_url and has_command:
            raise ValueError("mcp server config cannot define both url and command")
        if not has_url and not has_command:
            raise ValueError("mcp server config must define either url or command")
        if has_command and self.transport in {MCPServerTransport.SSE, MCPServerTransport.STREAMABLE_HTTP}:
            raise ValueError("mcp server transport with command source must be stdio")
        if has_url and self.transport == MCPServerTransport.STDIO:
            raise ValueError("mcp server transport with url source cannot be stdio")
        return self

    def infer_transport(self) -> MCPServerTransport:
        """Infers the effective transport from explicit value or source fields."""
        if self.transport is not None:
            return self.transport
        if self.command is not None:
            return MCPServerTransport.STDIO
        if self.url is not None:
            return MCPServerTransport.STREAMABLE_HTTP
        raise ValueError("cannot infer transport: must specify url or command")


class MCPConfig(BaseModel):
    """Represents the top-level structure of `mcp.json`."""

    model_config = ConfigDict(extra="ignore")

    mcpServers: dict[str, MCPServerConfig]
