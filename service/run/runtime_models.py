from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import RunRecord


@dataclass
class RunContext:
    run_id: str
    run: RunRecord
    artifact_dir: Path

    @classmethod
    async def load(cls, *, store: object, run_id: str) -> "RunContext | None":
        run = await store.get_run(run_id)
        if run is None:
            return None
        return cls(run_id=run_id, run=run, artifact_dir=Path(run.artifact_dir))
