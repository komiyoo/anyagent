from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .sqlalchemy_backend import SqlAlchemyEventStore, SqlAlchemyRunStore, SqlAlchemySessionStore

class MySQLRunStore(SqlAlchemyRunStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="mysql")

class MySQLSessionStore(SqlAlchemySessionStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="mysql")

class MySQLEventStore(SqlAlchemyEventStore):
    def __init__(self, *, engine: AsyncEngine) -> None:
        super().__init__(engine=engine, schema_name=None, dialect="mysql")
