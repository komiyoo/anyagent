from __future__ import annotations

from typing import Literal


PostgresSchemaPolicy = Literal["migrate", "runtime_create"]


async def ensure_postgres_schema_objects(
    *,
    postgres_dsn: str,
    postgres_schema: str,
    required_tables: list[str],
    create_statements: list[str],
    policy: PostgresSchemaPolicy,
) -> None:
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(postgres_dsn) as conn:
        async with conn.cursor() as cur:
            if policy == "runtime_create":
                await cur.execute(f"CREATE SCHEMA IF NOT EXISTS {postgres_schema}")
                for stmt in create_statements:
                    await cur.execute(stmt)
                await conn.commit()
                return

            await cur.execute(
                "SELECT to_regclass(%s)",
                (f"{postgres_schema}.schema_migrations",),
            )
            mig = await cur.fetchone()
            migrations_ready = bool(mig and mig[0])

            missing: list[str] = []
            for table in required_tables:
                await cur.execute("SELECT to_regclass(%s)", (f"{postgres_schema}.{table}",))
                row = await cur.fetchone()
                if not row or row[0] is None:
                    missing.append(table)
        await conn.commit()

    if migrations_ready and not missing:
        return

    missing_desc = ", ".join(missing) if missing else "schema_migrations"
    raise RuntimeError(
        "postgres schema is not ready; run `anyagent storage-migrate` first "
        f"(schema={postgres_schema}, missing={missing_desc}) "
        "or set POSTGRES_SCHEMA_POLICY=runtime_create for development fallback"
    )
