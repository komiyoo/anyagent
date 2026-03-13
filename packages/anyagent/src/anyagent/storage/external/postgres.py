from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .sqlalchemy_backend import SqlAlchemyEventStore, SqlAlchemyRunStore, SqlAlchemySessionStore

class PostgresRunStore(SqlAlchemyRunStore):
    def __init__(self, *, engine: AsyncEngine, schema_name: str = "public") -> None:
        super().__init__(engine=engine, schema_name=schema_name, dialect="postgresql")

class PostgresSessionStore(SqlAlchemySessionStore):
    def __init__(self, *, engine: AsyncEngine, schema_name: str = "public") -> None:
        super().__init__(engine=engine, schema_name=schema_name, dialect="postgresql")

class PostgresEventStore(SqlAlchemyEventStore):
    def __init__(self, *, engine: AsyncEngine, schema_name: str = "public") -> None:
        super().__init__(engine=engine, schema_name=schema_name, dialect="postgresql")
