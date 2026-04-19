from tests.support.service_flow_shared import *  # noqa: F401,F403


def test_slide_preview_endpoint_returns_html_when_slide_ready(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Incremental Preview",
            "project_id": "p-preview",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})

    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    resp = client.get(f"/v1/ppt/runs/{run_id}/slides/1/preview")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] == run_id
    assert payload["slide_no"] == 1
    assert payload["page_index"] == 0
    assert payload["slide_id"] == f"{run_id}-slide-0"
    assert isinstance(payload.get("html_preview"), str)
    assert "slide-preview-stage" in payload["html_preview"]


def test_slide_preview_endpoint_returns_conflict_when_slide_not_ready(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Preview Guard",
            "project_id": "p-preview-guard",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})

    resp = client.get(f"/v1/ppt/runs/{run_id}/slides/1/preview")
    assert resp.status_code == 409
    assert "slide preview not ready" in resp.json()["detail"]


def test_regenerate_slide_endpoint_publishes_final_preview_event(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Regenerate Preview",
            "project_id": "p-regenerate-preview",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    before = client.get(f"/v1/ppt/runs/{run_id}").json()
    resp = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/regenerate",
        json={"instruction": "精简标题", "preserve_style": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SLIDES_GENERATING"

    wait_status(client, run_id, {"SUCCEEDED"})
    after = client.get(f"/v1/ppt/runs/{run_id}").json()
    before_events = [
        event
        for event in before["events"]
        if event["event"] == "slide.generated" and event["payload"].get("slide_no") == 1
    ]
    after_events = [
        event
        for event in after["events"]
        if event["event"] == "slide.generated" and event["payload"].get("slide_no") == 1
    ]
    assert len(after_events) >= len(before_events) + 1
    payload = after_events[-1]["payload"]
    assert isinstance(payload.get("html_preview"), str)
    assert payload.get("preview_width") == 1280
    assert payload.get("preview_height") == 720
    assert payload.get("is_final") is True
