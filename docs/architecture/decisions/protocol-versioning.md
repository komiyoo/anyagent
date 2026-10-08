# Protocol Versioning

Status: Accepted

Date: 2026-05-30

Req: `requirements.md#req-7`

Scope: `anyagent.protocol.*`, schema bundle export, endpoint manifest, SDK conformance fixtures

## Context

`anyagent.protocol.*` is the wire-level SSOT for server, SDK, Studio and generated TypeScript types. The schema bundle already carries `protocol_version`, `schema_version` and changelog data via `packages/anyagent/src/anyagent/protocol/schema_export.py`, but release and review rules need a stable compatibility policy.

The repository also has generated consumers in `sdks/typescript/generated/` and shared conformance fixtures under `tests/fixtures/sdk_conformance/`. A protocol change can therefore be source-compatible in Python but still break SDK consumers if a public field is removed, made required, narrowed, or if an endpoint manifest changes.

## Decision

Use the exported schema bundle as the protocol artifact for compatibility review.

- `protocol_version` is the compatibility identifier for public wire behavior.
- `schema_version` identifies the deterministic bundle revision that SDK generators consumed.
- The changelog section in the bundle records notable protocol-surface changes.
- Public breaking changes are detected by comparing the previous generated bundle with the candidate bundle.
- CI runs `scripts/ci/run_protocol_schema_diff.sh`, which exports the candidate bundle and checks it with `scripts/protocol_schema_diff.py` against the base branch bundle.
- The first independent artifact form is a protocol manifest file in this repository, not a split package or separate repository.

## Breaking Changes

The diff guard treats these as breaking unless an explicit migration plan updates this ADR and the relevant TODO/acceptance documents:

- Removing a model or type adapter from the exported bundle.
- Removing a public field from an exported schema.
- Making an existing field required.
- Narrowing a JSON schema type or removing enum values.
- Removing an endpoint operation or changing its method, path, request model or response model.

Additive fields, additive enum values and new endpoint operations are allowed by default.

## Consequences

- Protocol-affecting PRs must regenerate generated SDK schema/types and keep conformance fixtures aligned.
- Runtime-only internal envelopes, such as replay observability export payloads, should stay outside `anyagent.protocol.*` unless they become public wire contracts.
- If a future release intentionally breaks compatibility, the change must bump `protocol_version`, update the changelog, cite the affected requirements, and include migration notes.

## Recorded Breaking Changes

- `0.2.0` (2026-10-07): removed `StorageComponentCapabilities.long_term_owner` from `/admin/storage/health` capabilities (Req: `requirements.md#req-3-1`). Its `anyagent-apps` value named a project that no longer exists, and `tier` already distinguishes reference from external backends. Migration: upgrade the server and the Python/TypeScript SDK together, because the model forbids extra fields. Details are in the bundle changelog in `schema_export.py`.

## References

- `packages/anyagent/src/anyagent/protocol/schema_export.py`
- `scripts/export_protocol_schema.py`
- `scripts/protocol_schema_diff.py`
- `tests/contract/test_protocol_schema_export.py`
- `docs/architecture/api/sdk-compatibility-matrix.md`
- `todo/protocol.md`
