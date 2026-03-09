CREATE TABLE IF NOT EXISTS {{schema}}.sessions (
  session_partition_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  session_key TEXT NOT NULL,
  snapshot_json JSONB NOT NULL,
  snapshot_version BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {{schema}}.runs (
  response_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  session_key TEXT NOT NULL,
  stream BOOLEAN NOT NULL,
  idempotency_key TEXT NULL UNIQUE,
  status TEXT NOT NULL,
  effective_status TEXT NOT NULL,
  created_at_ms BIGINT NOT NULL,
  updated_at_ms BIGINT NOT NULL,
  ended_at_ms BIGINT NULL,
  final_response_json JSONB NULL,
  error_json JSONB NULL
);

CREATE TABLE IF NOT EXISTS {{schema}}.event_runs (
  response_id TEXT PRIMARY KEY,
  next_seq BIGINT NOT NULL DEFAULT 0,
  done BOOLEAN NOT NULL DEFAULT FALSE,
  run_status TEXT NULL,
  effective_run_status TEXT NULL,
  response_json JSONB NULL,
  error_json JSONB NULL
);

CREATE TABLE IF NOT EXISTS {{schema}}.events (
  response_id TEXT NOT NULL,
  seq BIGINT NOT NULL,
  event_type TEXT NULL,
  payload_json JSONB NOT NULL,
  PRIMARY KEY (response_id, seq)
);
