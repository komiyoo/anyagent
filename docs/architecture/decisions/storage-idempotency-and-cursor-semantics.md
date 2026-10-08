# Storage Idempotency And Cursor Semantics

Status: Accepted

Date: 2026-05-30

Req: `requirements.md#req-3-1`

Scope: Run Store, Event Store, replay cursors, `/v1/responses` idempotency

## Context

anyagent supports stateless ingress and resumable execution. That requires two storage guarantees to remain stable across in-memory, local SQL and external PostgreSQL/Redis deployments:

- request retries with the same idempotency key must not start duplicate runs;
- event replay cursors must be monotonic and safe across disconnect/reconnect, cache misses and retention.

The storage model already has run records, event records, replay helpers and external SQL adapters. This ADR fixes the compatibility semantics that future adapters and runtimes must preserve.

## Decision

Idempotency is owned by the Run Store.

- The dedupe key is scoped to the logical run creation boundary, not to a transport connection.
- `idempotency_key` must resolve to the same `response_id` after a successful create.
- If a retry races with an in-progress run, the retry returns or streams the existing run state.
- Terminal response snapshots are cached outputs of the run, not separate sources of truth.
- PostgreSQL/MySQL uniqueness is the source of truth for external storage; Redis can be a hot cache but cannot be the only dedupe authority.

Replay cursors are owned by the Event Store.

- `seq` is run-local, starts at 1 and is monotonically increasing.
- `last_seq` means "return events with `seq > last_seq`".
- Gaps are allowed after retention or replay-only pruning; clients must not assume contiguous indexes.
- `next_last_seq` is the highest delivered event seq, or the highest known tail seq when no page items are available.
- `[DONE]` remains the stream terminal marker; typed run status remains the status source for completed/errored/cancelled state.
- Redis event TTL is a hot-cache lifecycle; durable replay retention is controlled by the primary event store policy.

## Adapter Requirements

- Adapters must validate and normalize boundary data into typed records before internal use.
- Adapters with a hot cache must write the durable store first, then refresh the cache best-effort.
- Cursor APIs must compare by `seq`, not by list index, so pruned events do not corrupt replay.
- Retention jobs may delete replay-grade payload events without renumbering retained events.
- If a backend cannot support a stronger guarantee, it must report the limitation through capability docs/tests instead of silently weakening the contract.

## Verification

- `tests/unit/server/test_idempotency.py`
- `tests/unit/server/test_storage_replay.py`
- `tests/unit/server/test_events_retention.py`
- `tests/acceptance/server/acceptance_builtin_server_smoke.py`
- `tests/contract/test_sse_protocol_contract.py`

## Consequences

- Future storage adapters must implement idempotency and cursor behavior before being marked production-capable.
- SDK and runtime replay code must tolerate seq gaps.
- Retention policy is compatible with replay clients because cursors are seq-based, not offset-based.

## References

- `packages/anyagent/src/anyagent/storage/replay.py`
- `packages/anyagent/src/anyagent/storage/contracts.py`
- `packages/anyagent/src/anyagent/server/responses/idempotency.py`
- `docs/architecture/storage/storage-minimal-design.md`
