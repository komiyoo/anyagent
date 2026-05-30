"""credential v2 tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "credentials",
        sa.Column("credential_id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("scope_level", sa.Text, primary_key=True),
        sa.Column("agent_id", sa.Text, nullable=True),
        sa.Column("session_key", sa.Text, nullable=True),
        sa.Column("agent_id_norm", sa.Text, sa.Computed("COALESCE(agent_id, '')", persisted=True), primary_key=True),
        sa.Column("session_key_norm", sa.Text, sa.Computed("COALESCE(session_key, '')", persisted=True), primary_key=True),
        sa.Column("value_ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotate_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("scope_level IN ('global', 'agent', 'session')", name="credentials_scope_level_chk"),
    )

    op.create_table(
        "credential_audit",
        sa.Column("audit_ref", sa.Text, primary_key=True),
        sa.Column("operation", sa.Text, nullable=False),
        sa.Column("credential_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=True),
        sa.Column("scope_level", sa.Text, nullable=True),
        sa.Column("agent_id", sa.Text, nullable=True),
        sa.Column("session_key", sa.Text, nullable=True),
        sa.Column("deleted", sa.Boolean, nullable=True),
        sa.Column("payload_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("credential_audit_credential_idx", "credential_audit", ["credential_id", "created_at"])


def downgrade() -> None:
    op.drop_index("credential_audit_credential_idx", table_name="credential_audit")
    op.drop_table("credential_audit")
    op.drop_table("credentials")
