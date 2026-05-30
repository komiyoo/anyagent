from __future__ import annotations

from anyagent.server.migrations import list_storage_migrations
from anyagent.storage.external.migrations import default_postgres_migrations_dir


def test_postgres_storage_migrations_are_owned_by_alembic() -> None:
    migrations = list_storage_migrations()
    versions_dir = default_postgres_migrations_dir()

    assert versions_dir.name == "versions"
    assert {migration.version for migration in migrations} >= {"0001_baseline_storage_core", "0002_credential_v2"}
    assert not list(versions_dir.parent.parent.parent.joinpath("server", "migrations").glob("*.sql"))
