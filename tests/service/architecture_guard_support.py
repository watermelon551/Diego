from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def iter_py_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path
