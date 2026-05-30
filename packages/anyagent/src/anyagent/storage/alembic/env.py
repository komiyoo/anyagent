"""Alembic environment configuration for anyagent storage migrations."""

from __future__ import annotations

import os
import re

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from anyagent.storage.alembic.orm import Base

config = context.config

target_metadata = Base.metadata


def _get_url() -> str:
    url = config.get_main_option("sqlalchemy.url", "")
    if not url:
        url = os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL") or ""
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _get_schema() -> str:
    schema = os.environ.get("POSTGRES_SCHEMA", "public").strip() or "public"
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", schema):
        raise ValueError("invalid POSTGRES_SCHEMA")
    return schema


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table_schema=_get_schema() if _get_schema() != "public" else None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        schema = _get_schema()
        if schema != "public":
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}"'))
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema if schema != "public" else None,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
