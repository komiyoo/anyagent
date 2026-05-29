# Run Scheduling And Lock Contract

Status: Accepted
Date: 2026-05-29
Req: `requirements.md#req-5`, `requirements.md#req-3-1`
Scope: Cross-node run scheduling, keyed serialization, resume, and cancel coordination.

## Decision

anyagent uses `session_partition_key = "{agent_id}::{session_key}"` as the distributed scheduling key for Response runs.

The lock contract is a renewable lease:

- `acquire(key, owner, ttl_ms, wait_timeout_ms) -> handle | None`
- `renew(key, owner, ttl_ms) -> bool`
- `release(key, owner) -> bool`

`key` is the `session_partition_key`; `owner` is the active `response_id` or a stable runtime owner derived from it. A node may execute a run only while it owns the lease. Loss of lease must stop the run path rather than allowing two writers to mutate the same session snapshot.

## Rationale

The server already treats Session as the conversation and serialization boundary. Cross-node scheduling must preserve the same behavior:

- same session partition: strictly one active run
- different session partitions: may run in parallel
- replay and resume: read from Event Store and Run Store, not node-local process memory
- cancel: mark the run terminal through Run Store CAS semantics; streaming callers replay terminal events from Event Store

This keeps the HTTP/SSE ingress stateless while letting any node resume tailing events or observe cancellation state.

## Backends

Reference backends must share the same contract:

- `inmemory`: single-process tests and local development
- `redis`: production hot-path lease using atomic `SET NX PX` plus owner-checked Lua renew/release
- `postgres`: production fallback lease using a SQL row keyed by `session_partition_key`, owner CAS, and expiry timestamps

Redis is preferred when configured because TTL expiry is native and fast. PostgreSQL is required as a storage-aligned adapter for environments that already run SQL but do not run Redis.

## Resume And Cancel Semantics

Resume is event-log based:

1. `POST /v1/responses` creates or reuses a `RunRecord` by idempotency key.
2. The executing node acquires the session lease and appends events with monotonically increasing `seq`.
3. Another node can serve `/v1/responses/{response_id}` or internal event replay from shared Run/Event stores.
4. If a client reconnects with `last_seq`, the server replays stored events and tails new events.

Cancel is terminal-state based:

1. Cancel uses Run Store CAS from `started` to `errored` with `error.code = "cancelled"`.
2. Only the lease owner can continue mutating the session snapshot.
3. Competing nodes observe the terminal run state and return/replay the cancelled state instead of starting a second execution.

## Consequences

- New scheduling code must depend on the `LeaseLock` contract rather than a specific Redis or SQL client.
- PostgreSQL and Redis adapters must be covered by shared contract tests for acquire conflict, renew, release, expiry, resume replay, and cancel CAS.
- Built-in server and distributed runtime should converge on the same lock contract even if they expose different HTTP wiring.
- Queueing and global concurrency lanes can be layered later; the P0 invariant is per-session keyed serialization.

## Evidence

- Runtime concepts define `session_partition_key` as the conversation serialization boundary: `docs/architecture/runtime/agent-server-runtime-entities.md`.
- Stateless service architecture defines lease locks, replay, resume, and cancellation as the cross-node reliability core: `docs/architecture/runtime/stateless-agent-service-architecture.md`.
- Storage runtime already exposes `LeaseLock` beside Run/Event/Session stores: `packages/anyagent/src/anyagent/storage/contracts.py`.
