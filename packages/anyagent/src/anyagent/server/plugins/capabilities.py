from __future__ import annotations

from anyagent.protocol.plugin_capabilities import PluginCapability, PluginCapabilityMatrix


def build_plugin_capability_matrix() -> PluginCapabilityMatrix:
    """Return the static plugin capability matrix for Gateway and Tool Runtime hosts."""

    return PluginCapabilityMatrix(
        manifest_schema="docs/schemas/plugin-manifest.schema.json",
        capabilities=[
            PluginCapability(
                capability="channels",
                host="gateway",
                status="preview",
                description="Inbound platform connector channel declarations for gateway integrations.",
                manifest_field="channels",
                registration_api="registerChannel",
                source="anyagent.plugins.api.AnyAgentPluginAPI",
            ),
            PluginCapability(
                capability="webhook_routes",
                host="gateway",
                status="preview",
                description="Plugin-provided webhook routes for platform callbacks.",
                registration_api="registerWebhookRoute",
                source="anyagent.plugins.api.AnyAgentPluginAPI",
            ),
            PluginCapability(
                capability="tools",
                host="gateway",
                status="preview",
                description="Tools registered into the built-in Agent Server runtime by loaded plugins.",
                manifest_field="tools",
                registration_api="registerTool",
                source="anyagent.tool_runtime.plugins.ToolRuntimePluginAPI",
            ),
            PluginCapability(
                capability="hooks",
                host="gateway",
                status="preview",
                description="Run lifecycle hooks invoked at response start and terminal completion.",
                manifest_field="hooks",
                source="anyagent.plugins.hooks.PluginHooks",
            ),
            PluginCapability(
                capability="middlewares",
                host="gateway",
                status="preview",
                description="Agent middleware classpaths that can be referenced from agent runtime config.",
                manifest_field="middlewares",
                source="anyagent.agent_runtime.middleware",
            ),
            PluginCapability(
                capability="skills",
                host="tool_runtime",
                status="preview",
                description="Skill package declarations validated for traceability in the plugin catalog.",
                manifest_field="skills",
                source="anyagent.plugins.loader._resolve_declared_capabilities",
            ),
            PluginCapability(
                capability="mcp_servers",
                host="tool_runtime",
                status="preview",
                description="MCP server declarations validated against MCPServerConfig.",
                manifest_field="mcp_servers",
                source="anyagent.protocol.mcp.MCPServerConfig",
            ),
            PluginCapability(
                capability="tools",
                host="tool_runtime",
                status="stable",
                description="Tools registered into the standalone Tool Runtime registry.",
                manifest_field="tools",
                registration_api="registerTool",
                source="anyagent.tool_runtime.plugins.ToolRuntimePluginAPI",
            ),
            PluginCapability(
                capability="middlewares",
                host="tool_runtime",
                status="preview",
                description="Middleware declarations are validated and loaded for catalog traceability.",
                manifest_field="middlewares",
                source="anyagent.plugins.loader._resolve_declared_capabilities",
            ),
            PluginCapability(
                capability="hooks",
                host="tool_runtime",
                status="preview",
                description="Lifecycle hooks are loaded for catalog traceability; gateway run invocation is the active hook host.",
                manifest_field="hooks",
                source="anyagent.plugins.hooks.PluginHooks",
            ),
        ],
    )
