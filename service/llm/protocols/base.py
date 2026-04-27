from __future__ import annotations

from typing import Awaitable, Callable

TokenCallback = Callable[[str], Awaitable[None]]

__all__ = ["TokenCallback"]

