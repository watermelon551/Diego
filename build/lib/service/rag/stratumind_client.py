from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class StratumindSearchError(RuntimeError):
    message: str
    code: str
    status_code: int
    retryable: bool
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


class StratumindSearchClient:
    def __init__(self, *, base_url: str, timeout_sec: float) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout_sec = max(1.0, float(timeout_sec))

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    async def search_text(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int,
        file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise StratumindSearchError(
                message="stratumind is not configured",
                code="STRATUMIND_UNAVAILABLE",
                status_code=503,
                retryable=False,
            )
        payload: dict[str, Any] = {
            "project_id": project_id,
            "query": query,
            "top_k": max(1, int(top_k)),
            "filters": {"file_ids": [item for item in (file_ids or []) if str(item).strip()]},
            "response": {
                "include_evidence": True,
                "include_planning_trace": True,
                "include_rewrite_trace": True,
            },
        }
        endpoint = f"{self.base_url}/search/text"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(endpoint, json=payload)
        except httpx.TimeoutException as exc:
            raise StratumindSearchError(
                message="stratumind search timeout",
                code="STRATUMIND_TIMEOUT",
                status_code=504,
                retryable=True,
                details={"reason": str(exc)},
            ) from exc
        except httpx.RequestError as exc:
            raise StratumindSearchError(
                message="stratumind request failed",
                code="STRATUMIND_REQUEST_ERROR",
                status_code=503,
                retryable=True,
                details={"reason": str(exc)},
            ) from exc

        body: dict[str, Any]
        try:
            body = response.json()
        except ValueError as exc:
            raise StratumindSearchError(
                message="stratumind returned invalid json",
                code="STRATUMIND_INVALID_RESPONSE",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
                details={"body": response.text[:400]},
            ) from exc
        if response.status_code >= 400:
            error_payload = body.get("error", {}) if isinstance(body, dict) else {}
            details = error_payload.get("details") if isinstance(error_payload.get("details"), dict) else None
            raise StratumindSearchError(
                message=str(error_payload.get("message") or "stratumind request failed"),
                code=str(error_payload.get("code") or "STRATUMIND_ERROR"),
                status_code=response.status_code,
                retryable=bool(error_payload.get("retryable", response.status_code >= 500)),
                details=details,
            )
        if not isinstance(body, dict):
            raise StratumindSearchError(
                message="stratumind response payload is not an object",
                code="STRATUMIND_INVALID_RESPONSE",
                status_code=response.status_code,
                retryable=False,
            )
        return body


def build_rag_context_snippets(
    response: dict[str, Any],
    *,
    max_items: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    results = response.get("results", [])
    if not isinstance(results, list):
        return []
    snippets: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        excerpt = " ".join(content.split())
        if len(excerpt) > max_chars:
            excerpt = excerpt[: max_chars - 3].rstrip(" ,;:.") + "..."
        page_number: int | None = None
        raw_page = item.get("page_number")
        if isinstance(raw_page, int) and raw_page > 0:
            page_number = raw_page
        raw_score = item.get("score", 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        snippets.append(
            {
                "chunk_id": str(item.get("chunk_id", "")).strip(),
                "file_id": str(item.get("file_id", "")).strip(),
                "filename": str(item.get("filename", "")).strip(),
                "source_type": str(item.get("source_type", "")).strip(),
                "source_scope": str(item.get("source_scope", "")).strip(),
                "score": score,
                "page_number": page_number,
                "excerpt": excerpt,
            }
        )
        if len(snippets) >= max_items:
            break
    return snippets
