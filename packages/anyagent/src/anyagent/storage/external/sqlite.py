from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .sqlalchemy_backend import SqlAlchemyEventStore, SqlAlchemyRunStore, SqlAlchemySessionStore


def create_sqlite_engine(db_path: Path) -> AsyncEngine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"check_same_thread": False},
    )


async def init_sqlite_schema(engine: AsyncEngine) -> None:
    """Create tables if they don't exist (WAL mode + schema)."""
    from .schema import build_storage_tables

    tables = build_storage_tables(schema_name=None, dialect="sqlite")
    async with engine.begin() as conn:
        await conn.run_sync(tables.metadata.create_all)
        await conn.execute(
            __import__("sqlalchemy").text("PRAGMA journal_mode=WAL")
        )
        await conn.execute(
            __import__("sqlalchemy").text("PRAGMA busy_timeout=5000")
        )


class SqliteRunStore(SqlAlchemyRunStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="sqlite")


class SqliteSessionStore(SqlAlchemySessionStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="sqlite")


class SqliteEventStore(SqlAlchemyEventStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="sqlite")
