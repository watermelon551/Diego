from __future__ import annotations

from tests.support.service_flow_shared import *  # noqa: F401,F403
import pytest


class _FakeScenePreviewResponse:
    def __init__(self, *, payload: dict | None = None, content: bytes = b"") -> None:
        self.status_code = 200
        self.text = "ok"
        self._payload = payload or {}
        self.content = content

    def json(self) -> dict:
        return self._payload


class _FakeScenePreviewClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, _url: str, json: dict) -> _FakeScenePreviewResponse:
        assert _url.endswith("/compile/bundles")
        if json["mode"] == "single_slide":
            return _FakeScenePreviewResponse(
                payload={
                    "state": "success",
                    "job_id": "scene-preview-1",
                    "artifacts": {
                        "preview_pages": [
                            {
                                "index": 0,
                                "slide_id": "slide-01",
                                "format": "svg",
                                "svg_data_url": "data:image/svg+xml;base64,scene-preview",
                                "width": 960,
                                "height": 540,
                            }
                        ]
                    },
                }
            )
        return _FakeScenePreviewResponse(
            payload={"state": "success", "job_id": "compile-job-1"}
        )

    async def get(self, _url: str) -> _FakeScenePreviewResponse:
        assert "/compile/jobs/" in _url
        return _FakeScenePreviewResponse(content=b"fake-pptx-from-pagevra")


class _PptdRegenerateReviewLLM(MockLLMClient):
    def __init__(self) -> None:
        self.review_rule_violations: list[list[str]] = []

    async def review_slide(self, **kwargs):
        self.review_rule_violations.append(list(kwargs["rule_violations"]))
        outline_node = kwargs["outline_node"]
        return GeneratedSlide(
            title="PPTD Reviewed Title",
            bullets=["Reviewed mechanism point", "Reviewed classroom cue"],
            citations=list(kwargs["candidate"].citations),
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
        )


def test_slide_preview_endpoint_returns_html_when_slide_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
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
    assert payload["preview_format"] == "svg"
    assert payload["svg_data_url"] == "data:image/svg+xml;base64,scene-preview"


def test_slide_scene_endpoint_rehydrates_missing_slide_js_from_run_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Scene Rehydrate",
            "project_id": "p-scene-rehydrate",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})

    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    run_detail = client.get(f"/v1/ppt/runs/{run_id}").json()
    slide_record = next(item for item in run_detail["slides"] if item["slide_no"] == 1)
    slide_js_path = Path(slide_record["js_path"])
    assert slide_js_path.is_file()
    slide_js_path.unlink()

    resp = client.get(f"/v1/ppt/runs/{run_id}/slides/1/scene")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["readonly"] is False
    assert payload["nodes"]
    assert slide_js_path.is_file()
    assert slide_js_path.read_text(encoding="utf-8") == slide_record["js_code"]


def test_slide_preview_endpoint_returns_conflict_when_slide_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
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


def test_regenerate_slide_endpoint_publishes_final_preview_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
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
        json={
            "instruction": "精简标题",
            "preserve_style": True,
            "expected_render_version": before["render_version"],
        },
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
    assert payload.get("svg_data_url") == "data:image/svg+xml;base64,scene-preview"
    assert payload.get("preview_width") == 960
    assert payload.get("preview_height") == 540
    assert payload.get("is_final") is True
    assert after["render_version"] == before["render_version"] + 1


def test_regenerate_slide_updates_pptd_project_without_legacy_slide_js(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_pptd_subprocess(args, cwd=None, **kwargs):
        command = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
        if "convert.sh" in command and isinstance(args, (list, tuple)):
            output = Path(args[args.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fake-pptx")
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="converted",
                stderr="",
            )
        return fake_subprocess_run(args, cwd=cwd, **kwargs)

    skill_dir = tmp_path / "pptx-skill"
    (skill_dir / "scripts" / "runtime").mkdir(parents=True)
    (skill_dir / "scripts" / "check.sh").write_text("", encoding="utf-8")
    (skill_dir / "scripts" / "convert.sh").write_text("", encoding="utf-8")
    (skill_dir / "scripts" / "runtime" / "tool.pptd").write_text("", encoding="utf-8")
    monkeypatch.setattr(orchestrator_mod.subprocess, "run", fake_pptd_subprocess)
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    llm = _PptdRegenerateReviewLLM()
    client = make_client(
        tmp_path,
        llm_client=llm,
        compile_provider="pptd",
        pptd_skill_dir=str(skill_dir),
        pptd_runner_mode="local",
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "PPTD Regenerate Rehydrate",
            "project_id": "p-pptd-regenerate-rehydrate",
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
    slide_one = next(item for item in before["slides"] if item["slide_no"] == 1)
    assert slide_one["js_path"] is None
    assert slide_one["js_code"] == ""
    pptd_path = Path(before["compile_js_path"])
    page_path = pptd_path.parent / "pages" / "slide-01.page"
    assert pptd_path.is_file()
    assert page_path.is_file()

    resp = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/regenerate",
        json={
            "instruction": "精简标题",
            "preserve_style": True,
            "expected_render_version": before["render_version"],
        },
    )
    assert resp.status_code == 200

    deadline = time.time() + 5
    after = before
    while time.time() < deadline:
        after = client.get(f"/v1/ppt/runs/{run_id}").json()
        if after["render_version"] > before["render_version"]:
            break
        assert not any(
            event["event"] == "slide.failed"
            and event["payload"].get("phase") == "slide.regenerate"
            for event in after["events"][len(before["events"]) :]
        )
        time.sleep(0.05)

    assert after["render_version"] == before["render_version"] + 1
    assert pptd_path.is_file()
    assert page_path.is_file()
    page_text = page_path.read_text(encoding="utf-8")
    assert "PPTD Reviewed Title" in page_text
    assert "Reviewed mechanism point" in page_text
    assert "重做要求：" not in page_text
    assert any("精简标题" in item for item in llm.review_rule_violations[0])
    assert after["compile_provider"] == "pptd"
    assert after["compile_bundle"]["entrypoint"] == "slides/compile_pptd_bundle.js"
    assert any(
        event["event"] == "compile.completed"
        and event["payload"].get("reason") == "single_slide_regenerate"
        for event in after["events"]
    )


def test_regenerate_slide_endpoint_rejects_stale_render_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Regenerate Conflict",
            "project_id": "p-regenerate-conflict",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    detail = client.get(f"/v1/ppt/runs/{run_id}").json()
    stale_version = detail["render_version"] + 1
    resp = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/regenerate",
        json={
            "instruction": "精简标题",
            "preserve_style": True,
            "expected_render_version": stale_version,
        },
    )

    assert resp.status_code == 409
    assert "render version conflict" in resp.json()["detail"]


def test_slide_scene_endpoint_returns_nodes_and_save_updates_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Scene Save",
            "project_id": "p-scene-save",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    scene_resp = client.get(f"/v1/ppt/runs/{run_id}/slides/1/scene")
    assert scene_resp.status_code == 200
    scene = scene_resp.json()
    assert scene["slide_id"] == f"{run_id}-slide-0"
    assert any(node["node_id"] == "text:config:title" for node in scene["nodes"])

    before_save = client.get(f"/v1/ppt/runs/{run_id}").json()
    save_resp = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/scene/save",
        json={
            "scene_version": scene["scene_version"],
            "operations": [
                {
                    "op": "replace_text",
                    "node_id": "text:config:title",
                    "value": "Scene Saved Title",
                }
            ],
        },
    )
    assert save_resp.status_code == 200
    payload = save_resp.json()
    assert payload["scene"]["nodes"][0]["text"] == "Scene Saved Title"
    assert payload["render_version"] == before_save["render_version"] + 1
    assert (
        payload["preview"]["svg_data_url"] == "data:image/svg+xml;base64,scene-preview"
    )

    run_detail = client.get(f"/v1/ppt/runs/{run_id}").json()
    slide_one = next(item for item in run_detail["slides"] if item["slide_no"] == 1)
    assert "Scene Saved Title" in slide_one["js_code"]
    assert any(
        event["event"] == "compile.completed"
        and event["payload"].get("reason") == "scene_save"
        for event in run_detail["events"]
    )


def test_slide_scene_save_updates_pptd_page_before_recompile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_pptd_subprocess(args, cwd=None, **kwargs):
        command = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
        if "convert.sh" in command and isinstance(args, (list, tuple)):
            output = Path(args[args.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fake-pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="converted", stderr="")
        return fake_subprocess_run(args, cwd=cwd, **kwargs)

    skill_dir = tmp_path / "pptx-skill"
    (skill_dir / "scripts" / "runtime").mkdir(parents=True)
    (skill_dir / "scripts" / "check.sh").write_text("", encoding="utf-8")
    (skill_dir / "scripts" / "convert.sh").write_text("", encoding="utf-8")
    (skill_dir / "scripts" / "runtime" / "tool.pptd").write_text("", encoding="utf-8")
    monkeypatch.setattr(orchestrator_mod.subprocess, "run", fake_pptd_subprocess)
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        compile_provider="pptd",
        pptd_skill_dir=str(skill_dir),
        pptd_runner_mode="local",
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "PPTD Scene Save",
            "project_id": "p-pptd-scene-save",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    scene = client.get(f"/v1/ppt/runs/{run_id}/slides/1/scene").json()
    editable_title = next(
        node
        for node in scene["nodes"]
        if node["label"] == "Title" and "replace_text" in node["edit_capabilities"]
    )
    save_resp = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/scene/save",
        json={
            "scene_version": scene["scene_version"],
            "operations": [
                {
                    "op": "replace_text",
                    "node_id": editable_title["node_id"],
                    "value": "PPTD Saved Title",
                }
            ],
        },
    )

    assert save_resp.status_code == 200
    run_detail = client.get(f"/v1/ppt/runs/{run_id}").json()
    pptd_path = Path(run_detail["compile_js_path"])
    page_text = (pptd_path.parent / "pages" / "slide-01.page").read_text(encoding="utf-8")
    assert "PPTD Saved Title" in page_text
    assert run_detail["compile_provider"] == "pptd"
    assert any(
        event["event"] == "compile.completed"
        and event["payload"].get("reason") == "pptd_scene_save"
        for event in run_detail["events"]
    )


def test_slide_scene_save_returns_conflict_for_stale_scene_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    monkeypatch.setattr(
        "service.run.engines.compile_engine.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeScenePreviewClient(),
    )
    client = make_client(
        tmp_path,
        pagevra_preview_enabled=True,
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Scene Conflict",
            "project_id": "p-scene-conflict",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    scene = client.get(f"/v1/ppt/runs/{run_id}/slides/1/scene").json()
    first_save = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/scene/save",
        json={
            "scene_version": scene["scene_version"],
            "operations": [
                {
                    "op": "replace_text",
                    "node_id": "text:config:title",
                    "value": "First Save",
                }
            ],
        },
    )
    assert first_save.status_code == 200

    stale_save = client.post(
        f"/v1/ppt/runs/{run_id}/slides/1/scene/save",
        json={
            "scene_version": scene["scene_version"],
            "operations": [
                {
                    "op": "replace_text",
                    "node_id": "text:config:title",
                    "value": "Second Save",
                }
            ],
        },
    )
    assert stale_save.status_code == 409
    assert "scene version conflict" in stale_save.json()["detail"]
