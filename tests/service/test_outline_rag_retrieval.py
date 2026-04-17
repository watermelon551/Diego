from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from service.app import create_app
from service.llm_client import MockLLMClient
from service.orchestrator import RunOrchestrator
from service.store import RunStore

from tests.support.runtime_helpers import make_settings, wait_status


class _FakeRAGClient:
    def __init__(self, *, results: list[dict[str, Any]], enabled: bool = True) -> None:
        self.enabled = enabled
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def search_text(
        self,
        *,
        project_id: str,
        query: str,
        top_k: int,
        file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "project_id": project_id,
                "query": query,
                "top_k": top_k,
                "file_ids": list(file_ids or []),
            }
        )
        return {
            "results": list(self.results),
            "total": len(self.results),
            "ranking_stage": "vector",
        }


class _SpyLLM(MockLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.outline_snippets: list[dict[str, Any]] = []

    async def generate_outline(self, **kwargs):
        self.outline_snippets = list(kwargs.get("rag_context_snippets") or [])
        return await super().generate_outline(**kwargs)


def _make_client(tmp_path: Path, *, rag_client: Any, llm_client: Any | None = None) -> TestClient:
    orchestrator = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm_client or MockLLMClient(),
        settings=make_settings(),
        rag_client=rag_client,
    )
    return TestClient(create_app(base_dir=tmp_path, orchestrator=orchestrator))


def test_outline_should_filter_selected_file_ids_for_rag_search(tmp_path: Path) -> None:
    rag_client = _FakeRAGClient(
        results=[
            {
                "chunk_id": "c-1",
                "file_id": "file-a",
                "filename": "a.md",
                "source_type": "text",
                "source_scope": "upload",
                "content": "TCP slow start ramps congestion window exponentially before congestion avoidance.",
                "score": 0.91,
                "page_number": 3,
            }
        ]
    )
    client = _make_client(tmp_path, rag_client=rag_client)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "TCP拥塞控制",
            "project_id": "p-rag-filter",
            "rag_source_ids": ["file-a", "file-b"],
            "template_style": "default",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert detail["outline"] is not None
    assert rag_client.calls
    assert rag_client.calls[0]["file_ids"] == ["file-a", "file-b"]


def test_outline_should_fail_when_selected_sources_have_no_retrieval_hits(tmp_path: Path) -> None:
    client = _make_client(tmp_path, rag_client=_FakeRAGClient(results=[]))
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "OSPF area design",
            "project_id": "p-rag-empty",
            "rag_source_ids": ["file-1"],
            "template_style": "default",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"FAILED"})
    assert detail["error_code"] == "OUTLINE_RAG_NO_MATCH_FOR_SELECTED_SOURCES"


def test_outline_should_continue_when_no_selected_sources_and_no_hits(tmp_path: Path) -> None:
    client = _make_client(tmp_path, rag_client=_FakeRAGClient(results=[]))
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "BGP route policy",
            "project_id": "p-rag-all-empty",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    events = [event for event in detail["events"] if event["event"] == "rag.retrieval.completed"]
    assert events
    assert events[-1]["payload"]["mode"] == "project_all"
    assert events[-1]["payload"]["hit_count"] == 0


def test_outline_should_pass_retrieved_snippets_to_llm(tmp_path: Path) -> None:
    spy_llm = _SpyLLM()
    rag_client = _FakeRAGClient(
        results=[
            {
                "chunk_id": "chunk-42",
                "file_id": "file-42",
                "filename": "routing.md",
                "source_type": "text",
                "source_scope": "upload",
                "content": "RIP converges slowly and is vulnerable to counting-to-infinity; split horizon mitigates loops.",
                "score": 0.88,
                "page_number": 5,
            }
        ]
    )
    client = _make_client(tmp_path, rag_client=rag_client, llm_client=spy_llm)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "RIP路由协议局限",
            "project_id": "p-rag-snippet",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert detail["outline"] is not None
    assert spy_llm.outline_snippets
    assert spy_llm.outline_snippets[0]["chunk_id"] == "chunk-42"
    assert "RIP converges slowly" in spy_llm.outline_snippets[0]["excerpt"]
