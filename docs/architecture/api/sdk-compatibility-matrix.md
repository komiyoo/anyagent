<!--
---
doc_kind: architecture
status: draft
tags: ["sdk", "protocol", "compatibility", "schema", "contract-tests"]
summary: Implemented SDK compatibility surfaces for the current single-repo, multi-package boundary.
req: ["requirements.md#req-4", "requirements.md#req-7"]
---
-->

# SDK Compatibility Matrix

This page tracks implemented compatibility surfaces between anyagent server, protocol schema exports, Studio and SDK packages.

## Current Matrix

| Surface | Package / Path | Status | Compatibility source | Minimum checks |
|---|---|---|---|---|
| Protocol schema bundle | `anyagent.protocol.schema_export` | Active | `scripts/export_protocol_schema.py --format bundle` | `tests/contract/test_protocol_schema_export.py` |
| OpenAPI export | `anyagent.protocol.schema_export` | Active | `scripts/export_protocol_schema.py --format openapi` | `tests/contract/test_protocol_schema_export.py` |
| Python SDK | `packages/anyagent/src/anyagent/agent_api_client.py` | Active | `anyagent.types` + `anyagent.protocol.*` | `tests/contract/`, `tests/acceptance/sdk/` |
| Studio | `packages/anyagent/studio/` | Active | OpenAI Responses API + `/internal/*` + `/admin/*` typed APIs | `npm run build`, server/SDK contract tests |
| TypeScript SDK | `sdks/typescript/` | Scaffolded | Protocol schema bundle | `npm --prefix sdks/typescript run smoke` |

## Compatibility Rules

- Protocol schema changes must update the schema bundle, server handlers, SDK facade and Studio consumers in the same change when they touch the same API path.
- Protocol exports carry both `protocol_version` (compatibility identifier) and `schema_version` (deterministic bundle revision); changelog entries live in the bundle so SDK/runtime generators can cite the protocol history they consumed.
- The TypeScript SDK generates wire models from the protocol schema bundle and keeps handwritten helpers in `sdks/typescript/src/client.ts`.
- SDKs must not import server runtime modules. Studio must not copy protocol shapes by hand.
- Contract tests protect schema export, StageEvent decoding, SSE parsing, and resource namespace request/response shapes.

## Export Command

```bash
uv run --project packages/anyagent python scripts/export_protocol_schema.py --out build/protocol-schema.json
```

Omit `--out` to print the deterministic JSON bundle to stdout.
Use `--format openapi` to export a generated OpenAPI 3.1 document from the same protocol models and endpoint manifest:

```bash
uv run --project packages/anyagent python scripts/export_protocol_schema.py --format openapi --out build/openapi.json
```

## Implemented TypeScript Surface

| Area | Implemented artifact | Validation |
|---|---|---|
| Generated schema | `sdks/typescript/generated/protocol-schema.json` | `npm --prefix sdks/typescript run smoke` |
| Generated types | `sdks/typescript/generated/protocol-types.ts` | `sdks/typescript/src/smoke/schema-smoke.ts` |
| Schema lookup | `sdks/typescript/src/schemaBundle.ts` | `sdks/typescript/src/smoke/schema-smoke.ts` |
| Runtime validation | `sdks/typescript/src/validate.ts` | `sdks/typescript/src/smoke/client-smoke.ts` |
| Fetch client | `sdks/typescript/src/client.ts` | `sdks/typescript/src/smoke/client-smoke.ts` |
| Shared fixtures | `tests/fixtures/sdk_conformance/core_surface.json` | `tests/contract/test_protocol_schema_export.py` |
| Minimum matrix | `tests/fixtures/sdk_conformance/minimum_matrix.json` | `tests/contract/test_protocol_schema_export.py` |

The TypeScript client resolves schema-backed helper paths and schemas through the protocol endpoint manifest. The contract suite guards against reintroducing handwritten `/internal/*`, `/admin/*`, `/v1/responses` or `anyagent.protocol.*` schema strings in `sdks/typescript/src/client.ts`.

```bash
npm --prefix sdks/typescript run smoke
```
