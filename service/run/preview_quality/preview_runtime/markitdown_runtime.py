from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

_MARKITDOWN_PLACEHOLDER_RE = re.compile(
    r"(xxxx|lorem|ipsum|placeholder|todo|this.*(page|slide).*layout)"
)


async def markitdown_check(
    *,
    run_subprocess: Callable[..., subprocess.CompletedProcess[str]],
    pptx_path: Path,
) -> tuple[bool, str | None]:
    text, issue = await markitdown_extract(
        run_subprocess=run_subprocess,
        pptx_path=pptx_path,
    )
    if issue:
        return False, issue
    if len(text) < 20:
        return False, "markitdown extracted too little content"
    return True, None


async def markitdown_extract(
    *,
    run_subprocess: Callable[..., subprocess.CompletedProcess[str]],
    pptx_path: Path,
) -> tuple[str, str | None]:
    result = await asyncio.to_thread(
        run_subprocess,
        [sys.executable, "-m", "markitdown", str(pptx_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return "", "markitdown qa failed"
    text = (result.stdout or "").strip()
    lowered = text.lower()
    if _MARKITDOWN_PLACEHOLDER_RE.search(lowered):
        return text, "markitdown detected placeholder text"
    if len(text) < 20:
        return text, "markitdown extracted too little content"
    return text, None
