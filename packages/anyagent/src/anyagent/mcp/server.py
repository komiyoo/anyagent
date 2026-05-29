from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx

from .auth import CredentialResolver, resolve_mcp_auth_env, resolve_mcp_auth_headers
from .models import MCPServerConfig, MCPServerTransport
from .util import sanitize_mcp_tool_name

logger = logging.getLogger("anyagent.mcp")

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception as _mcp_import_error:  # noqa: BLE001
    ClientSession = None  # type: ignore[assignment]
    sse_client = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
else:
    _mcp_import_error = None

try:
    from mcp.client.streamable_http import streamable_http_client as _streamable_http_client
except Exception:  # noqa: BLE001
    try:
        from mcp.client.streamable_http import streamablehttp_client as _streamable_http_client
    except Exception:  # noqa: BLE001
        try:
            from mcp.client.streamablehttp import streamablehttp_client as _streamable_http_client
        except Exception:  # noqa: BLE001
            _streamable_http_client = None


class MCPServerError(RuntimeError):
    """Represents MCP server connection or request failures."""


class MCPServer(ABC):
    """Defines the shared MCP server connection and request lifecycle."""

    def __init__(
        self,
        *,
        name: str,
        config: MCPServerConfig,
        agent_id: str,
        credential_store: CredentialResolver | None = None,
    ) -> None:
        self.name = name
        self.config = config
        self.agent_id = agent_id
        self.credential_store = credential_store

        self._connected = False
        self._last_active = time.monotonic()
        self._tools_cache: list[Any] | None = None
        self._lock = asyncio.Lock()
        self._session: Any | None = None
        self._exit_stack = AsyncExitStack()

    async def connect(self) -> None:
        """Connects to the MCP server and initializes the client session."""
        async with self._lock:
            if self._connected:
                return
            self._require_mcp_imports()
            try:
                streams_ctx = await self.create_streams()
                transport = await self._exit_stack.enter_async_context(streams_ctx)
                read_stream, write_stream, *_ = transport
                session = await self._exit_stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        timedelta(seconds=self.config.timeout_seconds),
                    )
                )
                await session.initialize()
                self._session = session
                self._connected = True
                self._touch()
            except Exception as e:  # noqa: BLE001
                await self._close_stack_safely()
                self._connected = False
                self._session = None
                raise MCPServerError(f"failed to connect MCP server {self.name}: {e}") from e

    async def disconnect(self) -> None:
        """Disconnects the MCP server and clears transient session state."""
        async with self._lock:
            await self._close_stack_safely()
            self._connected = False
            self._session = None

    async def ensure_connected(self) -> None:
        """Ensures the MCP server is connected before performing operations."""
        if not self._connected:
            await self.connect()

    async def list_tools(self) -> list[Any]:
        """Lists available tools from the MCP server with configured filtering."""
        await self.ensure_connected()
        assert self._session is not None
        self._touch()

        cursor: str | None = None
        tools: list[Any] = []
        while True:
            if cursor:
                try:
                    result = await self._session.list_tools(params={"cursor": cursor})
                except TypeError:
                    result = await self._session.list_tools()
            else:
                result = await self._session.list_tools()

            batch = getattr(result, "tools", None)
            if isinstance(batch, list):
                tools.extend(batch)

            cursor = self._next_cursor(result)
            if not cursor:
                break

        filtered = self._apply_tool_filter(tools)
        self._tools_cache = list(filtered)
        return filtered

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Calls one tool on the MCP server and returns raw MCP result."""
        await self.ensure_connected()
        assert self._session is not None
        self._touch()
        try:
            result = await self._session.call_tool(name, arguments or {})
        except Exception as e:  # noqa: BLE001
            await self.disconnect()
            raise MCPServerError(f"failed to call MCP tool {self.name}.{name}: {e}") from e
        self._touch()
        return result

    def is_idle(self, now: float) -> bool:
        """Returns True if idle timeout is reached for this server instance."""
        if self.config.idle_timeout_seconds <= 0:
            return False
        return (now - self._last_active) >= self.config.idle_timeout_seconds

    @abstractmethod
    async def create_streams(self) -> Any:
        """Creates transport streams context manager for the server."""

    def _touch(self) -> None:
        """Updates last activity timestamp to current monotonic time."""
        self._last_active = time.monotonic()

    def _apply_tool_filter(self, tools: list[Any]) -> list[Any]:
        """Applies allow/deny name filters to one MCP tool list."""
        tool_filter = self.config.tool_filter
        if tool_filter is None:
            return tools

        allow = {str(item).strip() for item in (tool_filter.allowed_tool_names or []) if str(item).strip()}
        deny = {str(item).strip() for item in (tool_filter.blocked_tool_names or []) if str(item).strip()}
        match_mode = tool_filter.match_mode

        out: list[Any] = []
        for tool in tools:
            raw_name = self._tool_name(tool)
            if not raw_name:
                continue
            names = self._filter_match_names(raw_name=raw_name, match_mode=match_mode)
            if allow and not names.intersection(allow):
                continue
            if names.intersection(deny):
                continue
            out.append(tool)
        return out

    @staticmethod
    def _filter_match_names(*, raw_name: str, match_mode: str) -> set[str]:
        """Returns the name variants that can satisfy one configured filter."""
        names: set[str] = set()
        if match_mode in {"raw", "both"}:
            names.add(raw_name)
        if match_mode in {"sanitized", "both"}:
            try:
                names.add(sanitize_mcp_tool_name(raw_name))
            except ValueError:
                pass
        return names

    @staticmethod
    def _tool_name(tool: Any) -> str:
        """Extracts a normalized tool name from an MCP tool object."""
        name = getattr(tool, "name", None)
        if isinstance(name, str):
            return name.strip()
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            return str(tool["name"]).strip()
        return ""

    @staticmethod
    def _next_cursor(result: Any) -> str | None:
        """Extracts pagination cursor from one `list_tools` result object."""
        cursor = getattr(result, "next_cursor", None)
        if cursor is None:
            cursor = getattr(result, "nextCursor", None)
        if isinstance(cursor, str) and cursor.strip():
            return cursor.strip()
        return None

    @staticmethod
    def _require_mcp_imports() -> None:
        """Raises a descriptive error when MCP optional dependency is missing."""
        if ClientSession is None:
            raise MCPServerError(f"mcp package is not available: {_mcp_import_error}")

    async def _close_stack_safely(self) -> None:
        """Closes async resources while suppressing secondary cleanup failures."""
        try:
            await self._exit_stack.aclose()
        except Exception:  # noqa: BLE001
            logger.debug("mcp server cleanup encountered an error", exc_info=True)
        self._exit_stack = AsyncExitStack()


class MCPServerStreamableHttp(MCPServer):
    """Implements MCP over Streamable HTTP transport."""

    async def create_streams(self) -> Any:
        """Creates Streamable HTTP transport streams with configured headers and timeout."""
        if _streamable_http_client is None:
            raise MCPServerError("mcp streamable_http transport is unavailable")
        if not self.config.url:
            raise MCPServerError(f"mcp server {self.name} missing url")

        headers = await resolve_mcp_auth_headers(self.config, self.credential_store, self.agent_id)
        timeout = httpx.Timeout(self.config.timeout_seconds)
        url = self.config.url

        @asynccontextmanager
        async def _ctx():
            async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
                async with _streamable_http_client(url, http_client=http_client) as streams:
                    yield streams

        return _ctx()


class MCPServerSse(MCPServer):
    """Implements MCP over legacy SSE transport."""

    async def create_streams(self) -> Any:
        """Creates SSE transport streams with configured headers and timeout."""
        if sse_client is None:
            raise MCPServerError("mcp sse transport is unavailable")
        if not self.config.url:
            raise MCPServerError(f"mcp server {self.name} missing url")

        headers = await resolve_mcp_auth_headers(self.config, self.credential_store, self.agent_id)
        return sse_client(
            url=self.config.url,
            headers=headers or None,
            timeout=self.config.timeout_seconds,
            sse_read_timeout=max(self.config.timeout_seconds, 60.0),
        )


class MCPServerStdio(MCPServer):
    """Implements MCP over stdio transport."""

    async def create_streams(self) -> Any:
        """Creates stdio transport streams by spawning the configured command."""
        if stdio_client is None or StdioServerParameters is None:
            raise MCPServerError("mcp stdio transport is unavailable")
        if not self.config.command:
            raise MCPServerError(f"mcp server {self.name} missing command")

        env = dict(os.environ)
        env.update(await resolve_mcp_auth_env(self.config, self.credential_store, self.agent_id))
        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args or []),
            env=env,
            cwd=self.config.cwd,
        )
        return stdio_client(params)


def create_mcp_server(
    *,
    name: str,
    config: MCPServerConfig,
    agent_id: str,
    credential_store: CredentialResolver | None = None,
) -> MCPServer:
    """Builds one concrete MCP server instance for a given server config."""
    transport = config.infer_transport()
    if transport == MCPServerTransport.STDIO:
        return MCPServerStdio(name=name, config=config, agent_id=agent_id, credential_store=credential_store)
    if transport == MCPServerTransport.SSE:
        return MCPServerSse(name=name, config=config, agent_id=agent_id, credential_store=credential_store)
    return MCPServerStreamableHttp(name=name, config=config, agent_id=agent_id, credential_store=credential_store)
