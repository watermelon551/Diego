from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .models import RunEvent, RunRecord, TemplateRecord


class RunStore:
    def __init__(self, base_dir: Path) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._templates: dict[str, TemplateRecord] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._lock = asyncio.Lock()
        self.base_dir = base_dir

    async def add_run(self, run: RunRecord) -> None:
        async with self._lock:
            self._runs[run.run_id] = run
            self._conditions[run.run_id] = asyncio.Condition()

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def update_run(self, run_id: str, updater: Callable[[RunRecord], None]) -> RunRecord:
        async with self._lock:
            run = self._runs[run_id]
            updater(run)
            condition = self._conditions[run_id]
        async with condition:
            condition.notify_all()
        return run

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        async with self._lock:
            run = self._runs[run_id]
            run.events.append(event)
            condition = self._conditions[run_id]
        async with condition:
            condition.notify_all()

    async def wait_for_event(self, run_id: str, cursor: int, timeout: float = 10.0) -> RunRecord:
        condition = self._conditions[run_id]
        async with condition:
            await asyncio.wait_for(condition.wait_for(lambda: len(self._runs[run_id].events) > cursor), timeout)
        async with self._lock:
            return self._runs[run_id]

    async def add_template(self, template: TemplateRecord) -> None:
        async with self._lock:
            self._templates[template.template_id] = template

    async def get_template(self, template_id: str) -> TemplateRecord | None:
        async with self._lock:
            return self._templates.get(template_id)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
