from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from .schema_migrations import apply_postgres_store_migrations


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
        self._initialized = False
        self._initialize_lock: Optional[asyncio.Lock] = None

    def _get_pool_lock(self) -> asyncio.Lock:
        if self._pool_lock is None:
            self._pool_lock = asyncio.Lock()
        return self._pool_lock

    def _get_initialize_lock(self) -> asyncio.Lock:
        if self._initialize_lock is None:
            self._initialize_lock = asyncio.Lock()
        return self._initialize_lock

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
        if self._initialized:
            return None
        pool = await self._ensure_pool()
        async with self._get_initialize_lock():
            if self._initialized:
                return None
            async with pool.acquire() as conn:
                await apply_postgres_store_migrations(conn)
            self._initialized = True
        return None
