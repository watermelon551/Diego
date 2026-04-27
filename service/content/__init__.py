from __future__ import annotations

__all__ = ["LongFormContentService"]


def __getattr__(name: str):
    if name == "LongFormContentService":
        from .service import LongFormContentService

        return LongFormContentService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

