<!--
---
doc_kind: architecture
status: stable
tags: ["plugins", "connectors", "lark", "discord", "telegram"]
summary: Platform connector ownership, official-package policy, and current connector status.
---
-->

# Platform Connectors

AnyAgent Core owns the connector contract, not every platform implementation.

Core truth:

- `anyagent.plugins.PluginManifest`
- `anyagent.plugins.schema_export.export_plugin_manifest_schema`
- `anyagent.plugins.load_plugins_from_roots`
- `anyagent.tool_runtime.plugins.ToolRuntimePluginAPI`
- `anyagent.protocol.plugins.PluginCatalogResponse`
- `anyagent.protocol.plugin_capabilities.PluginCapabilityMatrix`
- Tool Runtime `/admin/plugins/catalog`
- Core / Tool Runtime `/admin/plugins/capabilities`
- SDK `AnyAgent.admin.plugin_catalog()`
- CLI `anyagent plugin catalog`

Contract decision: `docs/architecture/decisions/plugin-connector-contract-v1.md`.

Manifest schema artifact: `docs/schemas/plugin-manifest.schema.json`.

Connector packages live outside `anyagent-apps` unless they are only example
documentation. A platform connector can be:

- an official upstream package or CLI integrated through skills
- an optional AnyAgent plugin package loaded with `--plugin-root`
- a gateway connector package for inbound platform events

## Current Status

| Platform | Current Core stance | Package / path | Notes |
|---|---|---|---|
| Lark / Feishu | Use official CLI and skills for outbound actions | `larksuite/cli`, `@larksuite/cli`, `lark-cli` | `anyagent-apps/plugins/lark-cli/README.md` is documentation only. Inbound webhook / gateway connectors are separate plugins or packages loaded through the Core plugin contract. |
| Discord | No in-repo framework implementation | optional connector package | Keep out of `anyagent-apps` until there is a real package with manifest, docs, schema, tests, and smoke validation. |
| Telegram | No in-repo framework implementation | optional connector package | Keep out of `anyagent-apps` until there is a real package with manifest, docs, schema, tests, and smoke validation. |

## Connector Acceptance

A connector is framework-grade only when all of these are true:

- It has a `plugin.json` manifest with stable `plugin_id`, `channels`, `entrypoint`,
  and docs/schema/test references.
- Registered tools are visible through `/admin/plugins/catalog`.
- Host support is visible through `/admin/plugins/capabilities`.
- SDK `AnyAgent.admin.plugin_catalog()` returns the same manifest and cite data.
- `anyagent plugin catalog` can inspect the connector without reading source code.
- Credentials are referenced by `credential_id` / `auth_ref`; plaintext secrets are
  not stored in agent config or plugin config.
- A targeted smoke proves manifest loading and at least one safe tool path.

`anyagent-apps` may keep example usage and business bundles, but it must not become
the source of truth for connector contracts or long-lived platform wrappers.
