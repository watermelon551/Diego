from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..models import RunEvent, RunRecord, TemplateRecord


def _to_json_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _from_json_payload(payload: Any) -> dict:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, (bytes, bytearray, memoryview)):
        payload = bytes(payload).decode("utf-8", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"payload must be a JSON object, got {type(payload).__name__}")


class RunStore:
    """
    In-memory run store (default dev mode).

    Kept under the legacy `RunStore` name for backwards compatibility with
    existing tests and imports.
    """

    def __init__(self, base_dir: Path) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._templates: dict[str, TemplateRecord] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._lock: Optional[asyncio.Lock] = None
        self.base_dir = base_dir

    async def initialize(self) -> None:
        return None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_condition(self, run_id: str) -> asyncio.Condition:
        condition = self._conditions.get(run_id)
        if condition is None:
            condition = asyncio.Condition()
            self._conditions[run_id] = condition
        return condition

    async def add_run(self, run: RunRecord) -> None:
        async with self._get_lock():
            self._runs[run.run_id] = run
            self._get_condition(run.run_id)

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._get_lock():
            return self._runs.get(run_id)

    async def list_runs(self) -> list[RunRecord]:
        async with self._get_lock():
            return list(self._runs.values())

    async def update_run(
        self,
        run_id: str,
        updater: Callable[[RunRecord], None],
    ) -> RunRecord:
        async with self._get_lock():
            run = self._runs[run_id]
            updater(run)
            condition = self._get_condition(run_id)
        async with condition:
            condition.notify_all()
        return run

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        async with self._get_lock():
            run = self._runs[run_id]
            run.events.append(event)
            condition = self._get_condition(run_id)
        async with condition:
            condition.notify_all()

    async def wait_for_event(
        self,
        run_id: str,
        cursor: int,
        timeout: float = 10.0,
    ) -> RunRecord:
        condition = self._get_condition(run_id)
        async with condition:
            await asyncio.wait_for(
                condition.wait_for(lambda: len(self._runs[run_id].events) > cursor),
                timeout,
            )
        async with self._get_lock():
            return self._runs[run_id]

    async def add_template(self, template: TemplateRecord) -> None:
        async with self._get_lock():
            self._templates[template.template_id] = template

    async def get_template(self, template_id: str) -> TemplateRecord | None:
        async with self._get_lock():
            return self._templates.get(template_id)


class PostgresRunStore:
    """
    Persistent run store backed by PostgreSQL.

    Tables are created lazily on first initialization.
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
            self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=8)
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

    def _serialize_run(self, run: RunRecord) -> str:
        payload = run.model_dump(mode="json")
        payload.pop("events", None)
        return _to_json_payload(payload)

    def _deserialize_run(self, run_payload: dict, events_payload: list[dict]) -> RunRecord:
        merged = dict(run_payload)
        merged["events"] = events_payload
        return RunRecord.model_validate(merged)

    async def _load_run(self, conn, run_id: str, *, for_update: bool) -> RunRecord | None:
        select_sql = (
            "SELECT run_json FROM diego_runs WHERE run_id=$1 FOR UPDATE"
            if for_update
            else "SELECT run_json FROM diego_runs WHERE run_id=$1"
        )
        run_row = await conn.fetchrow(select_sql, run_id)
        if run_row is None:
            return None
        events_rows = await conn.fetch(
            "SELECT event_json FROM diego_run_events WHERE run_id=$1 ORDER BY seq ASC",
            run_id,
        )
        return self._deserialize_run(
            _from_json_payload(run_row["run_json"]),
            [_from_json_payload(item["event_json"]) for item in events_rows],
        )

    async def add_run(self, run: RunRecord) -> None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO diego_runs(run_id, run_json)
                    VALUES($1, $2::jsonb)
                    ON CONFLICT (run_id) DO UPDATE
                    SET run_json=EXCLUDED.run_json, updated_at=NOW()
                    """,
                    run.run_id,
                    self._serialize_run(run),
                )
                await conn.execute(
                    "DELETE FROM diego_run_events WHERE run_id=$1",
                    run.run_id,
                )
                for event in run.events:
                    event_payload = event.model_dump(mode="json")
                    await conn.execute(
                        """
                        INSERT INTO diego_run_events(run_id, seq, event_json)
                        VALUES($1, $2, $3::jsonb)
                        """,
                        run.run_id,
                        int(event_payload.get("seq") or 0),
                        _to_json_payload(event_payload),
                    )

    async def get_run(self, run_id: str) -> RunRecord | None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._load_run(conn, run_id, for_update=False)

    async def list_runs(self) -> list[RunRecord]:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT run_id FROM diego_runs ORDER BY created_at ASC, run_id ASC"
            )
            runs: list[RunRecord] = []
            for row in rows:
                run = await self._load_run(conn, str(row["run_id"]), for_update=False)
                if run is not None:
                    runs.append(run)
            return runs

    async def update_run(
        self,
        run_id: str,
        updater: Callable[[RunRecord], None],
    ) -> RunRecord:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                run = await self._load_run(conn, run_id, for_update=True)
                if run is None:
                    raise KeyError(run_id)
                updater(run)
                await conn.execute(
                    """
                    UPDATE diego_runs
                    SET run_json=$2::jsonb, updated_at=NOW()
                    WHERE run_id=$1
                    """,
                    run_id,
                    self._serialize_run(run),
                )
                return run

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                run = await self._load_run(conn, run_id, for_update=True)
                if run is None:
                    raise KeyError(run_id)
                next_seq = int(
                    await conn.fetchval(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM diego_run_events WHERE run_id=$1",
                        run_id,
                    )
                    or 1
                )
                payload = event.model_dump(mode="json")
                payload["seq"] = next_seq
                await conn.execute(
                    """
                    INSERT INTO diego_run_events(run_id, seq, event_json)
                    VALUES($1, $2, $3::jsonb)
                    """,
                    run_id,
                    next_seq,
                    _to_json_payload(payload),
                )

    async def wait_for_event(
        self,
        run_id: str,
        cursor: int,
        timeout: float = 10.0,
    ) -> RunRecord:
        await self.initialize()
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            run = await self.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            if len(run.events) > cursor:
                return run
            await asyncio.sleep(self._event_poll_interval_sec)
        raise TimeoutError(f"wait_for_event timeout for run_id={run_id}")

    async def add_template(self, template: TemplateRecord) -> None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO diego_templates(template_id, template_json)
                VALUES($1, $2::jsonb)
                ON CONFLICT (template_id) DO UPDATE
                SET template_json=EXCLUDED.template_json, updated_at=NOW()
                """,
                template.template_id,
                _to_json_payload(template.model_dump(mode="json")),
            )

    async def get_template(self, template_id: str) -> TemplateRecord | None:
        await self.initialize()
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT template_json FROM diego_templates WHERE template_id=$1",
                template_id,
            )
            if row is None:
                return None
            return TemplateRecord.model_validate(_from_json_payload(row["template_json"]))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
