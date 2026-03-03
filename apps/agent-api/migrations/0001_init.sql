-- AnyAgent Agent API storage schema (v0)
-- This migration is schema-agnostic; the runner sets `search_path`.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- sessions: latest snapshot per session_partition_key
CREATE TABLE IF NOT EXISTS sessions (
  tenant_id               TEXT NULL,
  session_partition_key   TEXT NOT NULL,
  agent_id                TEXT NOT NULL,
  session_key             TEXT NOT NULL,

  snapshot_json           JSONB NOT NULL,
  snapshot_version        BIGINT NOT NULL DEFAULT 0,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (session_partition_key)
);
CREATE INDEX IF NOT EXISTS sessions_updated_at_idx ON sessions (updated_at);

-- runs: one run per response_id (AnyAgent uses response_id as run_id)
CREATE TABLE IF NOT EXISTS runs (
  tenant_id               TEXT NULL,
  response_id             TEXT NOT NULL,
  session_partition_key   TEXT NOT NULL,

  idempotency_key         TEXT NULL,
  stream                  BOOLEAN NOT NULL DEFAULT FALSE,

  status                  TEXT NOT NULL,
  error_json              JSONB NULL,

  final_response_json     JSONB NULL,
  last_event_seq          BIGINT NOT NULL DEFAULT 0,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at                TIMESTAMPTZ NULL,

  PRIMARY KEY (response_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS runs_idempotency_key_uq
  ON runs (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS runs_session_partition_idx ON runs (session_partition_key, created_at);

-- events: append-only per response_id with monotonic seq
CREATE TABLE IF NOT EXISTS events (
  tenant_id               TEXT NULL,
  response_id             TEXT NOT NULL,
  session_partition_key   TEXT NOT NULL,

  seq                     BIGINT NOT NULL,
  event_type              TEXT NOT NULL,
  payload_json            JSONB NOT NULL,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (response_id, seq)
);
CREATE INDEX IF NOT EXISTS events_session_partition_idx ON events (session_partition_key, created_at);
CREATE INDEX IF NOT EXISTS events_response_id_idx ON events (response_id, seq);

