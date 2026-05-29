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

CREATE TABLE IF NOT EXISTS {{schema}}.lease_locks (
  lock_key TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  expires_at_ms BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {{schema}}.telemetry_events (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  ts_ms BIGINT NULL,
  response_id TEXT NULL,
  agent_id TEXT NULL,
  session_key TEXT NULL,
  trace_id TEXT NULL,
  seq BIGINT NULL,
  level TEXT NULL,
  category TEXT NULL,
  status TEXT NULL,
  tool_name TEXT NULL,
  tool_call_id TEXT NULL,
  duration_ms DOUBLE PRECISION NULL,
  audit_ref TEXT NULL,
  message TEXT NULL,
  payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS telemetry_events_agent_session_idx
  ON {{schema}}.telemetry_events(agent_id, session_key, ts_ms);

CREATE INDEX IF NOT EXISTS telemetry_events_response_idx
  ON {{schema}}.telemetry_events(response_id, ts_ms);

CREATE INDEX IF NOT EXISTS telemetry_events_trace_idx
  ON {{schema}}.telemetry_events(trace_id, ts_ms);

CREATE INDEX IF NOT EXISTS telemetry_events_tool_idx
  ON {{schema}}.telemetry_events(tool_name, ts_ms);
