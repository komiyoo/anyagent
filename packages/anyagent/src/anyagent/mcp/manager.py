from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from anyagent.observability import emit_observability_event
from anyagent.protocol.stage_events import AnyAgentMcpServerLifecycleEvent, StageError, StageEvent

from .auth import CredentialResolver
from .models import MCPConfig
from .server import MCPServer, MCPServerError, create_mcp_server
from .util import mcp_call_result_to_output_text, mcp_tool_to_function_param

logger = logging.getLogger("anyagent.mcp")
StageEventSink = Callable[[StageEvent], Awaitable[None]]


class MCPServerManager:
    """Manages all MCP servers associated with one agent."""

    def __init__(
        self,
        *,
        agent_id: str,
        mcp_config: MCPConfig,
        credential_store: CredentialResolver | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.mcp_config = mcp_config
        self.credential_store = credential_store

        self._servers: dict[str, MCPServer] = {
            label: create_mcp_server(
                name=label,
                config=cfg,
                agent_id=agent_id,
                credential_store=credential_store,
            )
            for label, cfg in sorted(mcp_config.mcpServers.items())
            if cfg.enabled
        }
        self._idle_check_task: asyncio.Task[None] | None = None
        self._tool_source_names: dict[str, str] = {}

    async def ensure_all_connected(
        self,
        *,
        stage_event_sink: StageEventSink | None = None,
        response_id: str | None = None,
    ) -> list[MCPServer]:
        """Ensures each server is connected and returns healthy server instances."""
        self._start_idle_check_task()
        alive: list[MCPServer] = []
        for label, server in self._servers.items():
            was_connected = bool(getattr(server, "_connected", False))
            try:
                if not was_connected:
                    await self._emit_lifecycle_event(
                        stage_event_sink=stage_event_sink,
                        response_id=response_id,
                        event_type="anyagent.mcp.server.starting",
                        server=server,
                    )
                await server.ensure_connected()
                if not was_connected:
                    await self._emit_lifecycle_event(
                        stage_event_sink=stage_event_sink,
                        response_id=response_id,
                        event_type="anyagent.mcp.server.ready",
                        server=server,
                    )
                emit_observability_event(
                    "mcp.server.connected",
                    category="mcp",
                    level="info",
                    payload={"agent_id": self.agent_id, "server_label": label},
                )
                alive.append(server)
            except Exception as e:  # noqa: BLE001
                if not was_connected:
                    await self._emit_lifecycle_event(
                        stage_event_sink=stage_event_sink,
                        response_id=response_id,
                        event_type="anyagent.mcp.server.failed",
                        server=server,
                        error=e,
                    )
                emit_observability_event(
                    "mcp.server.connection_failed",
                    category="mcp",
                    level="warning",
                    payload={"agent_id": self.agent_id, "server_label": label, "error": str(e)},
                )
                logger.warning(
                    "mcp server connection failed; drop_failed enabled",
                    extra={"agent_id": self.agent_id, "server_label": label, "error": str(e)},
                )
        return alive

    async def list_all_tools(
        self,
        *,
        stage_event_sink: StageEventSink | None = None,
        response_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lists and converts tools from all connected MCP servers."""
        servers = await self.ensure_all_connected(stage_event_sink=stage_event_sink, response_id=response_id)
        out: list[dict[str, Any]] = []
        for server in servers:
            try:
                tools = await server.list_tools()
                emit_observability_event(
                    "mcp.tools.listed",
                    category="mcp",
                    level="info",
                    payload={"agent_id": self.agent_id, "server_label": server.name, "tool_count": len(tools)},
                )
            except Exception as e:  # noqa: BLE001
                emit_observability_event(
                    "mcp.tools.list_failed",
                    category="mcp",
                    level="warning",
                    payload={"agent_id": self.agent_id, "server_label": server.name, "error": str(e)},
                )
                logger.warning(
                    "mcp list_tools failed; skipping server",
                    extra={"agent_id": self.agent_id, "server_label": server.name, "error": str(e)},
                )
                continue
            for tool in tools:
                try:
                    function_param = mcp_tool_to_function_param(tool, server_label=server.name)
                    qualified_name = str(function_param.get("name", ""))
                    source_name = str(function_param.get("x_anyagent_source_name", "")).strip()
                    if qualified_name and source_name:
                        self._tool_source_names[qualified_name] = source_name
                    out.append(function_param)
                except Exception as e:  # noqa: BLE001
                    emit_observability_event(
                        "mcp.tool.conversion_failed",
                        category="mcp",
                        level="warning",
                        payload={"agent_id": self.agent_id, "server_label": server.name, "error": str(e)},
                    )
                    logger.warning(
                        "mcp tool conversion failed; skipping tool",
                        extra={
                            "agent_id": self.agent_id,
                            "server_label": server.name,
                            "error": str(e),
                        },
                    )
        return out

    async def _emit_lifecycle_event(
        self,
        *,
        stage_event_sink: StageEventSink | None,
        response_id: str | None,
        event_type: str,
        server: MCPServer,
        error: Exception | None = None,
    ) -> None:
        if stage_event_sink is None or not response_id:
            return
        transport: str | None = None
        try:
            transport = server.config.infer_transport().value
        except Exception:  # noqa: BLE001
            transport = None
        await stage_event_sink(
            AnyAgentMcpServerLifecycleEvent(
                type=event_type,  # type: ignore[arg-type]
                response_id=response_id,
                server_label=server.name,
                transport=transport,
                error=StageError(type=type(error).__name__, message=str(error)) if error is not None else None,
            )
        )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Routes one `mcp.<label>.<tool>` call and returns stringified tool output."""
        server_label, local_tool_name = self._parse_qualified_tool_name(tool_name)
        server = self._servers.get(server_label)
        if server is None:
            raise MCPServerError(f"unknown mcp server label: {server_label}")

        raw_local_tool_name = self._tool_source_names.get(tool_name, local_tool_name)
        result = await server.call_tool(raw_local_tool_name, arguments or {})
        emit_observability_event(
            "mcp.tool.called",
            category="mcp",
            level="info",
            payload={
                "agent_id": self.agent_id,
                "server_label": server_label,
                "tool_name": local_tool_name,
                "source_tool_name": raw_local_tool_name,
            },
        )
        return mcp_call_result_to_output_text(result)

    async def cleanup(self) -> None:
        """Stops idle checks and disconnects all managed MCP servers."""
        if self._idle_check_task is not None:
            self._idle_check_task.cancel()
            self._idle_check_task = None
        for server in self._servers.values():
            try:
                await server.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("mcp server cleanup ignored one disconnect failure", exc_info=True)

    async def _idle_check_loop(self) -> None:
        """Periodically disconnects idle servers based on each server timeout."""
        while True:
            await asyncio.sleep(60.0)
            now = time.monotonic()
            for label, server in self._servers.items():
                if not server.is_idle(now):
                    continue
                try:
                    await server.disconnect()
                    emit_observability_event(
                        "mcp.server.idle_disconnected",
                        category="mcp",
                        level="info",
                        payload={"agent_id": self.agent_id, "server_label": label},
                    )
                    logger.info(
                        "mcp server disconnected due to idle timeout",
                        extra={"agent_id": self.agent_id, "server_label": label},
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("idle disconnect failed", exc_info=True)

    def _start_idle_check_task(self) -> None:
        """Starts one background idle check task if it is not running yet."""
        if self._idle_check_task is not None and not self._idle_check_task.done():
            return
        self._idle_check_task = asyncio.create_task(self._idle_check_loop())

    @staticmethod
    def _parse_qualified_tool_name(tool_name: str) -> tuple[str, str]:
        """Parses a qualified tool name in the `mcp.<label>.<tool>` format."""
        if not isinstance(tool_name, str):
            raise MCPServerError("mcp tool name must be a string")
        parts = tool_name.split(".", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            raise MCPServerError(f"invalid mcp tool name: {tool_name}")
        label = parts[1].strip()
        local = parts[2].strip()
        if not label or not local:
            raise MCPServerError(f"invalid mcp tool name: {tool_name}")
        return label, local


class MCPManagerRegistry:
    """Provides global lazy manager initialization indexed by agent_id."""

    def __init__(self) -> None:
        self._managers: dict[str, MCPServerManager] = {}
        self._lock = asyncio.Lock()

    async def get_manager(
        self,
        *,
        agent_id: str,
        mcp_config: MCPConfig,
        credential_store: CredentialResolver | None = None,
    ) -> MCPServerManager:
        """Returns the manager for one agent, creating it lazily if needed."""
        async with self._lock:
            manager = self._managers.get(agent_id)
            if manager is not None:
                return manager
            manager = MCPServerManager(
                agent_id=agent_id,
                mcp_config=mcp_config,
                credential_store=credential_store,
            )
            self._managers[agent_id] = manager
            return manager

    async def cleanup_all(self) -> None:
        """Cleans up all managers and drops registry state."""
        async with self._lock:
            managers = list(self._managers.values())
            self._managers.clear()
        for manager in managers:
            await manager.cleanup()
