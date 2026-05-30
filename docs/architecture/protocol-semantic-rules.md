<!--
---
doc_kind: architecture
status: stable
tags: ["protocol", "schema", "semantic-rules", "sdk"]
summary: Protocol schema bundle 中非 JSON Schema 可表达规则的维护口径与当前规则索引。
req: ["requirements.md#req-7"]
---
-->

# Protocol Semantic Rules

`anyagent.protocol.*` 的主合同由 Pydantic models 和导出的 JSON Schema bundle 表达。少量规则无法稳定落进 JSON Schema，必须通过 `semantic_rules` 随 bundle 一起导出，供 SDK、Studio、contract tests 和后续 runtime 复用。

代码真源：

- 规则 registry：`packages/anyagent/src/anyagent/protocol/schema_export.py:301`
- 导出入口：`packages/anyagent/src/anyagent/protocol/schema_export.py:573`
- bundle 使用方：`sdks/typescript/src/schemaBundle.ts:54`
- TS smoke 覆盖：`sdks/typescript/src/smoke/schema-smoke.ts:44`

## 维护规则

- JSON Schema 能表达的字段类型、required、enum、bounds，优先留在 protocol model 上。
- 跨字段、递归 key policy、运行时别名一致性等 JSON Schema 难表达规则，放入 `SEMANTIC_RULES`。
- 每条 semantic rule 必须有稳定 `id`、`kind`、`mode`、`fields`、`description` 与 valid/invalid examples。
- 新增 semantic rule 必须同步 SDK smoke 或 contract test，确保消费侧能发现规则。
- 删除或改变 rule 语义视为 protocol surface 变化，需经过 schema diff / protocol versioning 审查。

## 当前规则索引

| Model | Rule id | Purpose |
|---|---|---|
| `anyagent.protocol.credential_vault.CredentialScope` | `credential_scope_agent_id_matches_level` | `level=agent` 时必须提供 `agent_id`，非 agent scope 时不得携带。 |
| `anyagent.protocol.mcp.MCPServerConfig` | `mcp_server_source_is_exactly_one_of_url_or_command` | MCP server source 必须在 URL 与 command 之间二选一，并与 transport 匹配。 |
| `anyagent.protocol.multi_agent.SpawnAgentArgs` | `spawn_agent_requires_consistent_agent_selector` | `agent_type` 作为 deprecated alias 时必须与 `agent_id` 一致。 |
| `anyagent.protocol.multi_agent.SendInputArgs` | `send_input_requires_message_or_items` | child thread 输入必须包含非空 message 或至少一个 item。 |
| `anyagent.protocol.tool_runtime.ToolContext` | `tool_context_rejects_plaintext_secret_fields` | Tool context 不允许递归携带 plaintext secret-like keys，只能通过 credential reference 表达。 |

## Related Contracts

- Protocol versioning ADR: [decisions/protocol-versioning.md](decisions/protocol-versioning.md)
- SDK compatibility matrix: [api/sdk-compatibility-matrix.md](api/sdk-compatibility-matrix.md)
- Contract tests: `tests/contract/test_protocol_schema_export.py`
