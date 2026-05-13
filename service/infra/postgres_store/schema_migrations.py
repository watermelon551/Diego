from __future__ import annotations

from typing import Final

POSTGRES_STORE_MIGRATIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "diego_postgres_store_v1",
        (
            """
            CREATE TABLE IF NOT EXISTS diego_runs (
                run_id TEXT PRIMARY KEY,
                run_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS diego_run_events (
                run_id TEXT NOT NULL REFERENCES diego_runs(run_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                event_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (run_id, seq)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_diego_run_events_run_seq
                ON diego_run_events(run_id, seq)
            """,
            """
            CREATE TABLE IF NOT EXISTS diego_templates (
                template_id TEXT PRIMARY KEY,
                template_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ),
    ),
)


async def apply_postgres_store_migrations(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS diego_store_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    rows = await conn.fetch(
        "SELECT version FROM diego_store_migrations ORDER BY version ASC"
    )
    applied_versions = {str(row["version"]) for row in rows}
    for version, statements in POSTGRES_STORE_MIGRATIONS:
        if version in applied_versions:
            continue
        async with conn.transaction():
            for statement in statements:
                await conn.execute(statement)
            await conn.execute(
                """
                INSERT INTO diego_store_migrations(version)
                VALUES($1)
                ON CONFLICT (version) DO NOTHING
                """,
                version,
            )
