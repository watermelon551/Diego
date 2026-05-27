from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from service.api.app import create_app
from service.config import Settings
from service.llm import MockLLMClient
from service.models import LongFormPlan
from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore

from tests.support.runtime_helpers import make_client, make_settings


def wait_content_status(
    client: TestClient, run_id: str, expected: set[str], timeout: float = 8.0
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/v1/content/runs/{run_id}").json()
        if data["status"] in expected:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} not in {expected} within {timeout}s")


def test_create_content_run_should_produce_plan_without_ppt_contract_fields(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/content/runs",
        json={
            "topic": "Photosynthesis mechanisms",
            "project_id": "proj-content-1",
            "target_section_count": 3,
            "audience": "high school learners",
            "purpose": "build conceptual understanding",
            "tone": "clear",
        },
    ).json()["run_id"]

    detail = wait_content_status(client, run_id, {"AWAITING_PLAN_CONFIRM"})
    assert detail["plan"]["version"] == 1
    assert len(detail["plan"]["sections"]) == 3
    assert detail["plan_history"][-1]["action"] == "drafted"
    assert "compile_result" not in detail
    assert "compile_bundle" not in detail
    assert "pptx_path" not in detail
    assert "output_format_hint" not in detail["research_report"]
    assert detail["research_report"]["canonical_output"] == "content_blocks_v1"
    events = [item["event"] for item in detail["events"]]
    assert "plan.completed" in events


def test_confirm_content_plan_should_update_then_generate_structured_draft(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/content/runs",
        json={
            "topic": "Cell division",
            "project_id": "proj-content-2",
            "target_section_count": 2,
        },
    ).json()["run_id"]
    drafted = wait_content_status(client, run_id, {"AWAITING_PLAN_CONFIRM"})
    base_version = drafted["plan"]["version"]
    updated_plan = LongFormPlan.model_validate(drafted["plan"])
    updated_plan.sections[0].title = "Cell cycle overview"
    updated_plan.sections[0].key_points = ["Interphase", "Mitosis checkpoints"]

    update_resp = client.post(
        f"/v1/content/runs/{run_id}/plan/confirm",
        json={
            "approved": False,
            "plan": updated_plan.model_dump(mode="json"),
            "base_version": base_version,
            "change_reason": "tighten the first section",
        },
    )
    assert update_resp.status_code == 200

    updated = wait_content_status(client, run_id, {"AWAITING_PLAN_CONFIRM"})
    assert updated["plan"]["version"] == base_version + 1
    assert updated["plan_history"][-1]["action"] == "updated"

    approve = client.post(
        f"/v1/content/runs/{run_id}/plan/confirm", json={"approved": True}
    )
    assert approve.status_code == 200
    final = wait_content_status(client, run_id, {"SUCCEEDED"})

    assert final["draft"]["version"] == 1
    assert final["draft"]["content_schema"] == "content_blocks_v1"
    assert len(final["draft"]["sections"]) == 2
    assert final["draft"]["sections"][0]["heading"] == "Cell cycle overview"
    assert final["draft"]["stats"]["section_count"] == 2
    assert "artifacts" not in final
    assert "markdown" not in final["draft"]


def test_revise_content_section_should_only_update_target_section_and_keep_citations_grounded(
    tmp_path: Path,
) -> None:
    class FakeRagClient:
        enabled = True

        async def search_text(self, *, project_id: str, query: str, top_k: int, file_ids=None):
            return {
                "total": 2,
                "ranking_stage": "mock",
                "results": [
                    {
                        "chunk_id": "chunk-11",
                        "content": "Chlorophyll absorbs light and transfers energy.",
                        "filename": "biology-notes.pdf",
                        "file_id": "file-1",
                    },
                    {
                        "chunk_id": "chunk-22",
                        "content": "ATP and NADPH power carbon fixation reactions.",
                        "filename": "biology-notes.pdf",
                        "file_id": "file-1",
                    },
                ],
            }

    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    orch.rag_client = FakeRagClient()
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))
    client.__enter__()

    run_id = client.post(
        "/v1/content/runs",
        json={
            "topic": "Photosynthesis",
            "project_id": "proj-content-rag",
            "rag_source_ids": ["file-1"],
            "target_section_count": 2,
        },
    ).json()["run_id"]
    wait_content_status(client, run_id, {"AWAITING_PLAN_CONFIRM"})
    client.post(f"/v1/content/runs/{run_id}/plan/confirm", json={"approved": True})
    final = wait_content_status(client, run_id, {"SUCCEEDED"})

    before = final["draft"]
    first_section = before["sections"][0]
    second_section = before["sections"][1]
    assert set(first_section["citations"]) == {"chunk-11", "chunk-22"}

    revise = client.post(
        f"/v1/content/runs/{run_id}/sections/{first_section['section_id']}/revise",
        json={
            "instruction": "emphasize light-dependent reactions",
            "base_revision": first_section["revision"],
            "preserve_structure": True,
        },
    )
    assert revise.status_code == 200
    payload = revise.json()
    assert payload["section"]["revision"] == first_section["revision"] + 1

    refreshed = client.get(f"/v1/content/runs/{run_id}").json()
    revised_first = refreshed["draft"]["sections"][0]
    unchanged_second = refreshed["draft"]["sections"][1]
    assert refreshed["draft"]["version"] == before["version"] + 1
    assert revised_first["revision"] == first_section["revision"] + 1
    assert revised_first["heading"] == first_section["heading"]
    assert unchanged_second == second_section
    events = [item["event"] for item in refreshed["events"]]
    assert "section.revised" in events


def test_revise_content_section_should_normalize_section_identity_and_preserve_structure(
    tmp_path: Path,
) -> None:
    class DriftedRevisionLLM(MockLLMClient):
        async def revise_section_draft(self, **kwargs):
            current = kwargs["current_section"]
            return type(current).model_validate(
                {
                    "section_id": "wrong-section",
                    "heading": "Unexpected rewrite heading",
                    "blocks": [
                        {
                            "kind": "paragraph",
                            "text": "Collapsed into a single paragraph by mistake.",
                        }
                    ],
                    "citations": [],
                    "revision": current.revision,
                }
            )

    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=DriftedRevisionLLM(),
        settings=make_settings(),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))
    client.__enter__()

    run_id = client.post(
        "/v1/content/runs",
        json={
            "topic": "Watershed restoration",
            "project_id": "proj-content-revise",
            "target_section_count": 2,
        },
    ).json()["run_id"]
    wait_content_status(client, run_id, {"AWAITING_PLAN_CONFIRM"})
    client.post(f"/v1/content/runs/{run_id}/plan/confirm", json={"approved": True})
    final = wait_content_status(client, run_id, {"SUCCEEDED"})

    section = final["draft"]["sections"][0]
    before_block_kinds = [block["kind"] for block in section["blocks"]]
    before_citations = list(section["citations"])
    revise = client.post(
        f"/v1/content/runs/{run_id}/sections/{section['section_id']}/revise",
        json={
            "instruction": "tighten the argument and keep the same structure",
            "base_revision": section["revision"],
            "preserve_structure": True,
        },
    )
    assert revise.status_code == 200
    payload = revise.json()
    assert payload["section"]["section_id"] == section["section_id"]
    assert payload["section"]["heading"] == section["heading"]
    assert [block["kind"] for block in payload["section"]["blocks"]] == before_block_kinds
    assert payload["section"]["citations"] == before_citations
    assert payload["section"]["revision"] == section["revision"] + 1


def test_structure_expansion_run_should_return_generic_units_without_product_semantics(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/content/runs",
        json={
            "content_kind": "structure_expansion",
            "generation_goal": "decompose watershed restoration priorities",
            "project_id": "proj-structure-1",
            "rag_source_ids": ["file-1"],
            "source_scope": {
                "mode": "selected_sources",
                "selected_source_ids": ["file-1"],
                "scope_note": "focus on provided restoration notes",
            },
            "evidence_refs": ["chunk-11"],
            "anchor_context": {
                "anchor_label": "restoration priorities",
                "anchor_summary": "expand the selected concept into child candidates",
                "related_labels": ["water quality", "habitat recovery"],
            },
            "constraints": {"max_units": 2},
            "requested_output_shape": "units",
        },
    ).json()["run_id"]

    detail = wait_content_status(client, run_id, {"SUCCEEDED"})
    assert detail["content_kind"] == "structure_expansion"
    result = detail["structure_expansion"]
    assert result["schema_version"] == "structure_expansion_v1"
    assert result["content_kind"] == "structure_expansion"
    assert len(result["units"]) == 2
    assert result["revision_targets"] == ["unit-1", "unit-2"]
    assert "draft" in detail and detail["draft"] is None
    assert "plan" in detail and detail["plan"] is None
    assert "selected_node_path" not in str(result)
    assert "mindmap" not in str(result).lower()
    events = [item["event"] for item in detail["events"]]
    assert "structure.expansion.completed" in events


def test_item_generation_run_should_return_generic_items_without_grading_or_quiz_semantics(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/content/runs",
        json={
            "content_kind": "item_generation",
            "generation_goal": "generate comprehension checks for photosynthesis",
            "project_id": "proj-items-1",
            "rag_source_ids": ["file-1"],
            "source_scope": {
                "mode": "selected_sources",
                "selected_source_ids": ["file-1"],
            },
            "evidence_refs": ["chunk-22"],
            "constraints": {"max_items": 2},
            "requested_output_shape": "items",
        },
    ).json()["run_id"]

    detail = wait_content_status(client, run_id, {"SUCCEEDED"})
    assert detail["content_kind"] == "item_generation"
    result = detail["item_generation"]
    assert result["schema_version"] == "item_generation_v1"
    assert result["content_kind"] == "item_generation"
    assert len(result["items"]) == 2
    assert result["revision_targets"] == ["item-1", "item-2"]
    assert "grading" not in str(result).lower()
    assert "quiz" not in str(result).lower()
    first = result["items"][0]
    assert first["stem"]
    assert first["choices"]
    assert first["expected_response"]
    assert first["expected_response_hints"]
    assert "preview" not in str(result).lower()
    assert "export" not in str(result).lower()
    events = [item["event"] for item in detail["events"]]
    assert "item.generation.completed" in events
