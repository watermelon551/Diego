from __future__ import annotations

import asyncio
from typing import Callable

from ...models import RunEvent, RunRecord
from ..store_support import from_json_payload, to_json_payload


class PostgresRunRecordsMixin:
    def _serialize_run(self, run: RunRecord) -> str:
        payload = run.model_dump(mode="json")
        payload.pop("events", None)
        return to_json_payload(payload)

    def _deserialize_run(
        self, run_payload: dict, events_payload: list[dict]
    ) -> RunRecord:
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
            from_json_payload(run_row["run_json"]),
            [from_json_payload(item["event_json"]) for item in events_rows],
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
                        to_json_payload(event_payload),
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
                    to_json_payload(payload),
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
