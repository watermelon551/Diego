from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Optional

from ..models import RunEvent, RunRecord, TemplateRecord


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
