from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .api.app import create_app

maybe_warn_legacy_import(legacy="service.app", replacement="service.api.app")

__all__ = ["create_app"]
