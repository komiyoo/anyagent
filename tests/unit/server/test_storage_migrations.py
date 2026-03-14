from __future__ import annotations

from anyagent.storage.external.migrations import _render_postgres_migration_sql


def test_render_postgres_migration_sql_replaces_schema_placeholder() -> None:
    rendered = _render_postgres_migration_sql(
        sql="CREATE TABLE IF NOT EXISTS {{schema}}.sessions (id text);",
        schema_name="anyagent_test",
    )

    assert rendered == 'CREATE TABLE IF NOT EXISTS "anyagent_test".sessions (id text);'
