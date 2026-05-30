# Unified Observability Replay Sink and Retention

Status: Accepted

Date: 2026-05-30

Req: `requirements.md#req-5-13`, `requirements.md#req-3-1`

Scope: Agent Server rendered prompt replay events, model-request replay events, tool-execution replay events, and operational observability sinks.

## Decision

Replay-grade observability data is split from the public protocol surface:

- The SDK and internal HTTP replay APIs continue to use `anyagent.protocol.*` response models.
- The operational sink envelope remains server-internal and is emitted through adapter interfaces, not exported as protocol schema.
- Rendered prompt context is governed by total serialized size, using `PersistenceConfig.persist_rendered_context` and `PersistenceConfig.rendered_context_max_bytes`.
- Model request payloads must be redacted before durable replay storage when they include injected credentials or authorization material.
- Replay event retention is independent from audit-event retention; replay payloads may be large and can expire earlier.
- Sink adapters are additive. The built-in path starts with stdout/logging and file-style JSONL adapters; OTel is an adapter behind the same internal envelope, not a direct dependency of the core loop.

## Rationale

The replay payloads behind `GET /internal/responses/{response_id}/prompt-context`, `tool-executions`, and `model-request` are operationally useful but large. Treating their sink format as a public wire contract would force schema-bundle compatibility promises onto data that should evolve with backend needs.

The internal envelope keeps observability exports testable and backend-neutral while the SDK-facing models remain stable in `anyagent.protocol.agent_api_internal`.

## Boundaries

- Public compatibility boundary: `anyagent.protocol.agent_api_internal` and generated SDK types.
- Server implementation boundary: `anyagent.observability`, `anyagent.server.telemetry_store`, `anyagent.persistence.*`, and event-store adapters.
- Storage lifecycle boundary: replay event TTL is configured separately from run/session retention.

## Consequences

- New sink adapters can be added without regenerating TypeScript protocol types.
- Contract tests should assert replay API response models and sink adapter behavior separately.
- Documentation and TODO evidence should cite protocol response models for SDK behavior, and this ADR for sink/retention policy.

## Evidence

- Prompt replay API model: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:153`
- Replay SDK helpers: `packages/anyagent/src/anyagent/agent_api_client.py:305`, `sdks/typescript/src/client.ts:491`
- Prompt replay persistence knobs: `packages/anyagent/src/anyagent/persistence/config.py:17`
- Observability summary counters: `packages/anyagent/src/anyagent/server/telemetry_store.py:343`
- Existing observability sink fan-out: `packages/anyagent/src/anyagent/observability.py:13`
