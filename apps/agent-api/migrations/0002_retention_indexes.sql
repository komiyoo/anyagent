-- Retention/TTL maintenance indexes (v0)
-- Helps batch cleanup scripts avoid full table scans.

CREATE INDEX IF NOT EXISTS runs_ended_at_idx ON runs (ended_at);

