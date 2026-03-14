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
  session_partition_key TEXT NOT NULL,
  idempotency_key TEXT NULL UNIQUE,
  stream BOOLEAN NOT NULL,
  status TEXT NOT NULL,
  last_event_seq BIGINT NOT NULL DEFAULT 0,
  final_response_json JSONB NULL,
  error_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ NULL
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
  session_partition_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (response_id, seq)
);
