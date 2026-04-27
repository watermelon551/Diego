from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def to_json_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def from_json_payload(payload: Any) -> dict:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, (bytes, bytearray, memoryview)):
        payload = bytes(payload).decode("utf-8", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"payload must be a JSON object, got {type(payload).__name__}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
