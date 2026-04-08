from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(base_dir=tmp_path))


def wait_status(client: TestClient, run_id: str, expected: set[str], timeout: float = 4.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/v1/ppt/runs/{run_id}").json()
        if data["status"] in expected:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} not in {expected} within {timeout}s")


def test_create_run_and_validation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/v1/ppt/runs", json={"project_id": "p1"}).status_code == 422

    resp = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "AI 101",
            "project_id": "p1",
            "rag_source_ids": ["chunk-1", "chunk-2"],
            "template_style": "clean",
            "target_slide_count": 3,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OUTLINE_DRAFTING"


def test_confirm_gate_and_success_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Data Platform",
            "project_id": "p2",
            "rag_source_ids": ["a", "b", "c"],
            "template_style": "business",
            "target_slide_count": 4,
        },
    ).json()["run_id"]

    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 409

    waiting = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert waiting["outline"]["version"] == 1

    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 200
    final_data = wait_status(client, run_id, {"SUCCEEDED"})

    assert final_data["pptx_path"] and Path(final_data["pptx_path"]).exists()
    assert final_data["compile_js_path"] and Path(final_data["compile_js_path"]).exists()
    assert len(final_data["slides"]) == 4
    assert set(final_data["citation_map"].keys()) == {"1", "2", "3", "4"}


def test_event_stream_has_required_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Observability",
            "project_id": "p3",
            "rag_source_ids": ["s1", "s2"],
            "template_style": "default",
            "target_slide_count": 2,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    with client.stream("GET", f"/v1/ppt/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())

    assert "event: outline.token" in body
    assert "event: outline.completed" in body
    assert "event: slide.generated" in body
    assert "event: compile.completed" in body


def test_slide_retry_and_compile_failure(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    retry_run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "FAIL_SLIDE_2 retry demo",
            "project_id": "p4",
            "rag_source_ids": ["x"],
            "template_style": "default",
            "target_slide_count": 3,
        },
    ).json()["run_id"]
    wait_status(client, retry_run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{retry_run_id}/outline/confirm", json={"approved": True})
    retry_final = wait_status(client, retry_run_id, {"SUCCEEDED"})
    statuses = {slide["slide_no"]: slide["status"] for slide in retry_final["slides"]}
    assert statuses[2].startswith("ok_after_retry")

    fail_run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "FAIL_COMPILE",
            "project_id": "p5",
            "rag_source_ids": ["x"],
            "template_style": "default",
            "target_slide_count": 2,
        },
    ).json()["run_id"]
    wait_status(client, fail_run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{fail_run_id}/outline/confirm", json={"approved": True})
    failed = wait_status(client, fail_run_id, {"FAILED"})

    assert failed["error_code"].startswith("COMPILE_ERROR")
    assert failed["failed_stage"] == "COMPILING"
    assert "run.failed" in [event["event"] for event in failed["events"]]
