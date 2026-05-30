<!--
---
doc_kind: adr
status: accepted
date: 2026-05-30
tags: ["plugins", "connectors", "tool-runtime", "gateway"]
summary: Plugin and connector packages use one manifest schema with host-specific capability surfaces.
---
-->

# Plugin Connector Contract v1

Status: accepted

Req: `requirements.md#req-6`

Scope: `anyagent.plugins`, `anyagent.protocol.plugins`, `anyagent.protocol.plugin_capabilities`, `anyagent.server.app`, `anyagent.tool_runtime.server`

## Decision

AnyAgent uses one Plugin Manifest v1 schema for both plugins and platform connectors. A single `plugin.json` may declare `channels`, `skills`, `mcp_servers`, `tools`, `middlewares`, and `hooks`; host support is described separately by the Plugin Capability Matrix.

The public contract has three surfaces:

- Manifest schema artifact: `docs/schemas/plugin-manifest.schema.json`, exported by `anyagent.plugins.schema_export.export_plugin_manifest_schema()`.
- Runtime catalog: `/admin/plugins/catalog`, modeled by `anyagent.protocol.plugins.PluginCatalogResponse`.
- Capability matrix: `/admin/plugins/capabilities`, modeled by `anyagent.protocol.plugin_capabilities.PluginCapabilityMatrix`.

## Rationale

Connectors and plugins share packaging needs: stable identity, docs/schema/test citations, optional configuration schema, and host-specific registration. Splitting them into unrelated manifest contracts would force duplicate metadata and make SDK/CLI discovery noisier. A unified manifest keeps package discovery simple while the capability matrix states what each host actually supports.

## Current Boundary

Gateway host:

- Loads plugin roots through `anyagent serve --plugin-root`.
- Registers plugin tools into the built-in runtime as preview capability.
- Invokes `on_agent_start` and `on_agent_end` hooks around `/v1/responses` runs.
- Keeps channels and webhook route registration planned.

Tool Runtime host:

- Loads plugin roots through `anyagent tool-runtime serve --plugin-root`.
- Registers plugin tools as stable capability.
- Validates declarative skills, MCP servers, middlewares, and hooks for catalog traceability.

Reference implementation: `packages/anyagent/src/anyagent/plugins/builtin/lifecycle_echo/`.

## Consequences

- `anyagent.protocol.*` remains free of `anyagent.plugins` imports; the manifest schema is exported as a standalone plugin artifact.
- SDKs can rely on the protocol bundle for catalog and capability responses, and on `docs/schemas/plugin-manifest.schema.json` for authoring `plugin.json`.
- Connector packages should cite their manifest, docs, schemas, and tests in `/admin/plugins/catalog`.
