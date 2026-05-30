from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BIGINT, JSON, TEXT, Boolean, Column, DateTime, MetaData, String, Table, func


@dataclass(slots=True, frozen=True)
class StorageTables:
    metadata: MetaData
    runs: Table
    sessions: Table
    events: Table
    leases: Table
    credentials: Table
    credential_audit: Table


def build_storage_tables(*, schema_name: str | None = None, dialect: str = "postgresql") -> StorageTables:
    metadata = MetaData()
    identity_type = _identity_column_type(dialect)
    key_type = _key_column_type(dialect)
    status_type = _status_column_type(dialect)
    event_type = _event_column_type(dialect)
    runs = Table(
        "runs",
        metadata,
        Column("response_id", identity_type, primary_key=True),
        Column("session_partition_key", key_type, nullable=False),
        Column("idempotency_key", key_type, nullable=True),
        Column("stream", Boolean, nullable=False, default=False),
        Column("status", status_type, nullable=False),
        Column("last_event_seq", BIGINT, nullable=False, default=0),
        Column("final_response_json", JSON, nullable=True),
        Column("error_json", JSON, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
        Column("ended_at", DateTime(timezone=True), nullable=True),
        schema=schema_name,
    )
    sessions = Table(
        "sessions",
        metadata,
        Column("session_partition_key", key_type, primary_key=True),
        Column("agent_id", key_type, nullable=False),
        Column("session_key", key_type, nullable=False),
        Column("snapshot_json", JSON, nullable=False),
        Column("snapshot_version", BIGINT, nullable=False, default=0),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
        schema=schema_name,
    )
    events = Table(
        "events",
        metadata,
        Column("response_id", identity_type, primary_key=True),
        Column("seq", BIGINT, primary_key=True),
        Column("session_partition_key", key_type, nullable=False),
        Column("event_type", event_type, nullable=False),
        Column("payload_json", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema=schema_name,
    )
    leases = Table(
        "lease_locks",
        metadata,
        Column("lock_key", key_type, primary_key=True),
        Column("owner", key_type, nullable=False),
        Column("expires_at_ms", BIGINT, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
        schema=schema_name,
    )
    credentials = Table(
        "credentials",
        metadata,
        Column("credential_id", key_type, primary_key=True),
        Column("kind", key_type, primary_key=True),
        Column("scope_level", String(length=32), primary_key=True),
        Column("agent_id", key_type, nullable=True),
        Column("session_key", key_type, nullable=True),
        Column("value_ciphertext", _binary_column_type(dialect), nullable=False),
        Column("metadata_json", JSON, nullable=False, default={}),
        Column("expires_at", DateTime(timezone=True), nullable=True),
        Column("rotate_before", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
        schema=schema_name,
    )
    credential_audit = Table(
        "credential_audit",
        metadata,
        Column("audit_ref", key_type, primary_key=True),
        Column("operation", String(length=64), nullable=False),
        Column("credential_id", key_type, nullable=False),
        Column("kind", key_type, nullable=True),
        Column("scope_level", String(length=32), nullable=True),
        Column("agent_id", key_type, nullable=True),
        Column("session_key", key_type, nullable=True),
        Column("deleted", Boolean, nullable=True),
        Column("payload_json", JSON, nullable=False, default={}),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema=schema_name,
    )
    return StorageTables(
        metadata=metadata,
        runs=runs,
        sessions=sessions,
        events=events,
        leases=leases,
        credentials=credentials,
        credential_audit=credential_audit,
    )


def _identity_column_type(dialect: str):
    if dialect == "mysql":
        return String(length=255)
    return TEXT


def _key_column_type(dialect: str):
    if dialect == "mysql":
        return String(length=255)
    return TEXT


def _status_column_type(dialect: str):
    if dialect == "mysql":
        return String(length=64)
    return TEXT


def _event_column_type(dialect: str):
    if dialect == "mysql":
        return String(length=128)
    return TEXT


def _json_column_type(dialect: str):
    if dialect == "sqlite":
        return JSON
    return JSON


def _binary_column_type(dialect: str):
    from sqlalchemy import LargeBinary

    return LargeBinary
