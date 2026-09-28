# AnyAgent TypeScript SDK

This directory contains the in-repo TypeScript client used by Studio through a
`file:` dependency. Release CI does not build or publish it.

It does not hand-write protocol shapes. The generated schema bundle comes from
the Python protocol source of truth:

```bash
uv run --project packages/anyagent python scripts/export_protocol_schema.py --out sdks/typescript/generated/protocol-schema.json
```

The scaffold currently exposes a tiny schema registry helper, generates
`generated/protocol-types.ts`, and runs a smoke test over the schema plus
generated declarations. It also includes a fetch-based `AnyAgentClient`
for typed control-plane paths with runtime response validation. It also covers
Responses `create` / `stream` / `retrieve` / `cancel`, events list,
tool execution replay, model request replay, agents list/get, tools catalog,
skills list, prompt bundle preview,
observability summary/runs/timeline/metrics/tools/errors/trace, admin
storage/tool/plugin catalog, credential set/list/delete, agent create/get,
agent file list/update, agent skill import/install/update, and agent
skills/config update. Runtime validation currently covers JSON Schema expressible constraints
plus explicit Pydantic-only semantic rules for `CredentialScope`,
`MCPServerConfig`, `SpawnAgentArgs`, `SendInputArgs`, and `ToolContext`.
Future work can broaden admin coverage and add new semantic rules as protocol
models gain validators.

The smoke test reads shared protocol fixture payloads from
`tests/fixtures/sdk_conformance/core_surface.json`. Python contract tests
validate the same payloads against the Pydantic protocol models, so the TS
client smoke and Python protocol contract stay tied to one conformance source.
The fixture also carries request negative cases that both Python and TS must
reject before a request leaves the SDK boundary. TS smoke fixture loading and
negative-case assertions live in `src/smoke/conformanceFixture.ts`.

## Commands

```bash
npm --prefix sdks/typescript run generate:schema
npm --prefix sdks/typescript run generate:types
npm --prefix sdks/typescript run build
npm --prefix sdks/typescript run smoke
```
