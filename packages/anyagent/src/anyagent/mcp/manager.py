from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from anyagent.observability import emit_observability_event
from anyagent.protocol.stage_events import AnyAgentMcpServerLifecycleEvent, StageError, StageEvent

from anyagent.protocol.mcp import MCPServerConfig, MCPServerTransport

from .auth import CredentialResolver
from .models import MCPConfig
from .server import MCPServer, MCPServerError, create_mcp_server
from .session_pool import MCPStdioConnectionPool, PoolKey
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
        stdio_pool: MCPStdioConnectionPool | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.mcp_config = mcp_config
        self.credential_store = credential_store
        self._stdio_pool = stdio_pool

        enabled = {label: cfg for label, cfg in sorted(mcp_config.mcpServers.items()) if cfg.enabled}

        # stdio servers are pooled per (agent, server, session); only their configs are
        # held here and connections are borrowed from the shared pool on demand. HTTP/SSE
        # servers are cheap and owned directly by this manager for its whole lifetime.
        self._stdio_configs: dict[str, MCPServerConfig] = {}
        self._servers: dict[str, MCPServer] = {}
        for label, cfg in enabled.items():
            if stdio_pool is not None and self._is_stdio(cfg):
                self._stdio_configs[label] = cfg
            else:
                self._servers[label] = create_mcp_server(
                    name=label,
                    config=cfg,
                    agent_id=agent_id,
                    credential_store=credential_store,
                )
        self._idle_check_task: asyncio.Task[None] | None = None
        self._tool_source_names: dict[str, str] = {}

    @staticmethod
    def _is_stdio(config: MCPServerConfig) -> bool:
        try:
            return config.infer_transport() == MCPServerTransport.STDIO
        except Exception:  # noqa: BLE001
            return False

    def _pool_key(self, label: str, session_key: str | None) -> PoolKey:
        return (self.agent_id, label, session_key)

    async def _acquire_server(self, label: str, *, session_key: str | None) -> MCPServer:
        """Resolves one server by label: pooled stdio connection or owned HTTP/SSE server."""
        owned = self._servers.get(label)
        if owned is not None:
            return owned
        cfg = self._stdio_configs.get(label)
        if cfg is None or self._stdio_pool is None:
            raise MCPServerError(f"unknown mcp server label: {label}")

        def _factory() -> MCPServer:
            return create_mcp_server(
                name=label,
                config=cfg,
                agent_id=self.agent_id,
                credential_store=self.credential_store,
            )

        return await self._stdio_pool.acquire(self._pool_key(label, session_key), _factory)

    def _all_labels(self) -> list[str]:
        return sorted({*self._servers.keys(), *self._stdio_configs.keys()})

    async def ensure_all_connected(
        self,
        *,
        session_key: str | None = None,
        stage_event_sink: StageEventSink | None = None,
        response_id: str | None = None,
    ) -> list[MCPServer]:
        """Ensures each server is connected and returns healthy server instances."""
        self._start_idle_check_task()
        alive: list[MCPServer] = []
        for label in self._all_labels():
            owned = self._servers.get(label)
            was_connected = bool(getattr(owned, "_connected", False)) if owned is not None else False
            try:
                if not was_connected:
                    await self._emit_lifecycle_event(
                        stage_event_sink=stage_event_sink,
                        response_id=response_id,
                        event_type="anyagent.mcp.server.starting",
                        server_label=label,
                    )
                server = await self._acquire_server(label, session_key=session_key)
                await server.ensure_connected()
                if not was_connected:
                    await self._emit_lifecycle_event(
                        stage_event_sink=stage_event_sink,
                        response_id=response_id,
                        event_type="anyagent.mcp.server.ready",
                        server_label=label,
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
                        server_label=label,
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
        session_key: str | None = None,
        stage_event_sink: StageEventSink | None = None,
        response_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lists and converts tools from all connected MCP servers."""
        servers = await self.ensure_all_connected(
            session_key=session_key,
            stage_event_sink=stage_event_sink,
            response_id=response_id,
        )
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
        server_label: str,
        server: MCPServer | None = None,
        error: Exception | None = None,
    ) -> None:
        if stage_event_sink is None or not response_id:
            return
        transport: str | None = None
        config = server.config if server is not None else self._config_for_label(server_label)
        if config is not None:
            try:
                transport = config.infer_transport().value
            except Exception:  # noqa: BLE001
                transport = None
        await stage_event_sink(
            AnyAgentMcpServerLifecycleEvent(
                type=event_type,  # type: ignore[arg-type]
                response_id=response_id,
                server_label=server_label,
                transport=transport,
                error=StageError(type=type(error).__name__, message=str(error)) if error is not None else None,
            )
        )

    def _config_for_label(self, label: str) -> MCPServerConfig | None:
        owned = self._servers.get(label)
        if owned is not None:
            return owned.config
        return self._stdio_configs.get(label)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any], *, session_key: str | None = None) -> str:
        """Routes one `mcp.<label>.<tool>` call and returns stringified tool output."""
        server_label, local_tool_name = self._parse_qualified_tool_name(tool_name)
        server = await self._acquire_server(server_label, session_key=session_key)

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
        """Stops idle checks and disconnects this manager's owned (non-pooled) servers.

        Pooled stdio connections are owned by the shared MCPStdioConnectionPool and are
        cleaned up via the pool, not here.
        """
        if self._idle_check_task is not None:
            self._idle_check_task.cancel()
            self._idle_check_task = None
        for server in self._servers.values():
            try:
                await server.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("mcp server cleanup ignored one disconnect failure", exc_info=True)

    async def _idle_check_loop(self) -> None:
        """Periodically disconnects idle owned (non-pooled) servers based on each timeout."""
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
    """Provides global lazy manager initialization indexed by agent_id.

    A single shared MCPStdioConnectionPool is injected into every manager so stdio
    connections are pooled and LRU-bounded across all agents and sessions.
    """

    def __init__(self, *, stdio_pool: MCPStdioConnectionPool | None = None) -> None:
        self._managers: dict[str, MCPServerManager] = {}
        self._lock = asyncio.Lock()
        self._stdio_pool = stdio_pool if stdio_pool is not None else MCPStdioConnectionPool()

    @property
    def stdio_pool(self) -> MCPStdioConnectionPool:
        return self._stdio_pool

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
                stdio_pool=self._stdio_pool,
            )
            self._managers[agent_id] = manager
            return manager

    async def cleanup_all(self) -> None:
        """Cleans up all managers, the shared stdio pool, and drops registry state."""
        async with self._lock:
            managers = list(self._managers.values())
            self._managers.clear()
        for manager in managers:
            await manager.cleanup()
        await self._stdio_pool.cleanup_all()
