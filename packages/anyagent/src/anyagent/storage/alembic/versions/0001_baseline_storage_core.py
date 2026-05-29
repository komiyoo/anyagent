"""baseline: existing storage core tables

Revision ID: 0001
Revises: None
Create Date: 2026-05-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_partition_key", sa.Text, primary_key=True),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("session_key", sa.Text, nullable=False),
        sa.Column("snapshot_json", JSONB, nullable=False),
        sa.Column("snapshot_version", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "runs",
        sa.Column("response_id", sa.Text, primary_key=True),
        sa.Column("session_partition_key", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=True, unique=True),
        sa.Column("stream", sa.Boolean, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("last_event_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("final_response_json", JSONB, nullable=True),
        sa.Column("error_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "event_runs",
        sa.Column("response_id", sa.Text, primary_key=True),
        sa.Column("next_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("done", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("run_status", sa.Text, nullable=True),
        sa.Column("effective_run_status", sa.Text, nullable=True),
        sa.Column("response_json", JSONB, nullable=True),
        sa.Column("error_json", JSONB, nullable=True),
    )

    op.create_table(
        "events",
        sa.Column("response_id", sa.Text, nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("session_partition_key", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("response_id", "seq"),
    )

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("ts_ms", sa.BigInteger, nullable=True),
        sa.Column("response_id", sa.Text, nullable=True),
        sa.Column("agent_id", sa.Text, nullable=True),
        sa.Column("session_key", sa.Text, nullable=True),
        sa.Column("trace_id", sa.Text, nullable=True),
        sa.Column("seq", sa.BigInteger, nullable=True),
        sa.Column("level", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=True),
        sa.Column("tool_name", sa.Text, nullable=True),
        sa.Column("tool_call_id", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Double, nullable=True),
        sa.Column("audit_ref", sa.Text, nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("payload_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("telemetry_events_agent_session_idx", "telemetry_events", ["agent_id", "session_key", "ts_ms"])
    op.create_index("telemetry_events_response_idx", "telemetry_events", ["response_id", "ts_ms"])
    op.create_index("telemetry_events_trace_idx", "telemetry_events", ["trace_id", "ts_ms"])
    op.create_index("telemetry_events_tool_idx", "telemetry_events", ["tool_name", "ts_ms"])


def downgrade() -> None:
    op.drop_index("telemetry_events_tool_idx")
    op.drop_index("telemetry_events_trace_idx")
    op.drop_index("telemetry_events_response_idx")
    op.drop_index("telemetry_events_agent_session_idx")
    op.drop_table("telemetry_events")
    op.drop_table("events")
    op.drop_table("event_runs")
    op.drop_table("runs")
    op.drop_table("sessions")
