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
| **Chatwoot** | Built-in reference implementation ✅ | `anyagent.plugins.builtin.chatwoot_connector` | Inbound channel connector with webhook receiver, HMAC signature verification, outbound message delivery, handoff, and conversation lifecycle events. Serves as the reference pattern for all platform connectors. See [Chatwoot Connector README](../../../packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/README.md). |
| Lark / Feishu | Use official CLI and skills for outbound actions | `larksuite/cli`, `@larksuite/cli`, `lark-cli` | `anyagent-apps/plugins/lark-cli/README.md` is documentation only. Inbound webhook / gateway connectors are separate plugins or packages loaded through the Core plugin contract. |
| Discord | No in-repo framework implementation | optional connector package | Keep out of `anyagent-apps` until there is a real package with manifest, docs, schema, tests, and smoke validation. |
| Telegram | No in-repo framework implementation | optional connector package | Keep out of `anyagent-apps` until there is a real package with manifest, docs, schema, tests, and smoke validation. |
| Intercom | No in-repo framework implementation | optional connector package | Connector contract supports Intercom via `ConnectorWebhookAuth` / `ConnectorOutboundDelivery` / `ConnectorHandoff` interfaces. |

## Connector Contract Interfaces

The Gateway layer defines platform-agnostic connector contracts in
`anyagent.gateway.connector_contracts`. Any platform connector implements
these interfaces to integrate with the anyagent framework:

| Interface | Purpose | Required |
|---|---|---|
| `ConnectorWebhookAuth` | Inbound webhook signature/payload verification | Yes (for inbound channels) |
| `ConnectorOutboundDelivery` | Send agent replies back to the platform | Yes (for messaging channels) |
| `ConnectorHandoff` | Execute platform-side human handoff | Optional |
| `PlatformConversationEvent` | Inject platform conversation lifecycle events into anyagent event store | Optional |
| `HandoffOutputItem` | Agent-level structured signal to trigger handoff | Optional |
| `gateway.handoff` | Tool-based human handoff signal executed through active connector context | Optional |

Key design principles:
- **Platform-agnostic**: Contracts work for Chatwoot, Intercom, Zendesk, Telegram, etc.
- **Credential-safe**: Secrets go through Credential Vault (`credential_id` refs), never hardcoded.
- **Plugin-native**: Connectors are loaded as `--plugin-root` plugins with `plugin.json` manifests.

### Handoff Signaling

AnyAgent currently supports two handoff signaling styles at the framework layer:

- `HandoffOutputItem`: structured output item for connector-aware post-processing.
- `gateway.handoff`: tool-based signal that stays compatible with the OpenAI Responses
  function-call path and executes through the active connector in `ToolContext.channel`.

For inbound webhook connectors, `gateway.handoff` is the most compatible main-path
option because it reuses the existing Tool Runtime manifest/execute contract instead
of requiring the upstream provider response schema to accept custom output item types.

For Chatwoot, the connector mutates conversation status in exactly two places
(both governed by `ANYAGENT_CHATWOOT_STATUS_CHANGES`, default `true` since
0.4.18): handoff toggles the conversation to `open`, and after the bot delivers
a reply a `pending` conversation is opened so bot-handled conversations show up
in the default Open list instead of Pending. Opting out with
`ANYAGENT_CHATWOOT_STATUS_CHANGES=false` disables all `toggle_status` calls
while keeping assignment and the AI summary private note; message delivery is
unaffected.

### Session Key Convention

```
{platform}:{account_id}:{conversation_id}
```

Examples:
- `chatwoot:1:42` — Chatwoot account 1, conversation 42
- `telegram:123456` — Telegram chat 123456
- `intercom:conv_abc` — Intercom conversation conv_abc

Helpers: `chatwoot_session_key()`, `telegram_session_key()`, `intercom_session_key()`
in `anyagent.gateway.connector_contracts`.

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
