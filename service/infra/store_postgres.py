from __future__ import annotations

from .postgres_store import (
    PostgresRunRecordsMixin,
    PostgresStoreRuntimeMixin,
    PostgresTemplateRecordsMixin,
)


class PostgresRunStore(
    PostgresStoreRuntimeMixin,
    PostgresRunRecordsMixin,
    PostgresTemplateRecordsMixin,
):
    """Thin compatibility facade for the postgres-backed run store."""


__all__ = ["PostgresRunStore"]
