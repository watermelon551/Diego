from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional


class PostgresStoreRuntimeMixin:
    """
    Shared PostgreSQL runtime and schema initialization for the run store.
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        database_url: str,
        event_poll_interval_sec: float = 0.5,
    ) -> None:
        self.base_dir = base_dir
        self._database_url = database_url
        self._event_poll_interval_sec = max(0.05, float(event_poll_interval_sec))
        self._pool = None
        self._pool_lock: Optional[asyncio.Lock] = None

    def _get_pool_lock(self) -> asyncio.Lock:
        if self._pool_lock is None:
            self._pool_lock = asyncio.Lock()
        return self._pool_lock

    async def _ensure_pool(self):
        if self._pool is not None:
            return self._pool
        async with self._get_pool_lock():
            if self._pool is not None:
                return self._pool
            try:
                import asyncpg  # type: ignore
            except Exception as exc:  # pragma: no cover - import guard
                raise RuntimeError(
                    "asyncpg is required when DIEGO_RUN_STORE=postgres"
                ) from exc
            self._pool = await asyncpg.create_pool(
                self._database_url, min_size=1, max_size=8
            )
        return self._pool

    async def initialize(self) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diego_runs (
                    run_id TEXT PRIMARY KEY,
                    run_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS diego_run_events (
                    run_id TEXT NOT NULL REFERENCES diego_runs(run_id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    event_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (run_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_diego_run_events_run_seq
                    ON diego_run_events(run_id, seq);
                CREATE TABLE IF NOT EXISTS diego_templates (
                    template_id TEXT PRIMARY KEY,
                    template_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
