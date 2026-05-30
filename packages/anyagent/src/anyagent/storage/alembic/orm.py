"""Unified SQLAlchemy ORM models for anyagent storage.

All tables are defined here as the single source of truth for Alembic
auto-generation and runtime queries. The legacy `schema.py` (Core tables)
remains for backward compatibility but new code should import from here.

Design principle: only fundamental storage primitives live here.
Derived/rendered/assembled data (rendered prompt context, tool execution
details, model request logs) are stored as event payloads in the `events`
table and assembled by service-layer code.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Computed, DateTime, Double, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    session_partition_key: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_key: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    snapshot_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Run(Base):
    __tablename__ = "runs"

    response_id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_partition_key: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    stream: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    final_response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventRun(Base):
    __tablename__ = "event_runs"

    response_id: Mapped[str] = mapped_column(Text, primary_key=True)
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Event(Base):
    __tablename__ = "events"

    response_id: Mapped[str] = mapped_column(Text, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_partition_key: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    ts_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    response_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    level: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Double, nullable=True)
    audit_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("telemetry_events_agent_session_idx", "agent_id", "session_key", "ts_ms"),
        Index("telemetry_events_response_idx", "response_id", "ts_ms"),
        Index("telemetry_events_trace_idx", "trace_id", "ts_ms"),
        Index("telemetry_events_tool_idx", "tool_name", "ts_ms"),
    )


class Credential(Base):
    __tablename__ = "credentials"

    credential_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    scope_level: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id_norm: Mapped[str] = mapped_column(Text, Computed("COALESCE(agent_id, '')", persisted=True), primary_key=True)
    session_key_norm: Mapped[str] = mapped_column(Text, Computed("COALESCE(session_key, '')", persisted=True), primary_key=True)
    value_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotate_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CredentialAudit(Base):
    __tablename__ = "credential_audit"

    audit_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    credential_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("credential_audit_credential_idx", "credential_id", "created_at"),
    )
