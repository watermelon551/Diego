from __future__ import annotations

from tests.support.service_flow_shared import *  # noqa: F401,F403
import service.run.engines.compile_engine as compile_engine_mod

def test_healthz_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "diego"}

def test_missing_llm_env_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError):
        load_settings(env_file="tests/.missing.env")

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
            "generation_mode": "scratch",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OUTLINE_DRAFTING"

def test_create_run_from_prompt_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.post(
        "/v1/ppt/runs/prompt",
        json={
            "prompt": "AI Agents for Product Teams",
            "project_id": "p-prompt",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OUTLINE_DRAFTING"
    detail = wait_status(client, data["run_id"], {"AWAITING_OUTLINE_CONFIRM"})
    assert len(detail["outline"]["nodes"]) == 3
    assert detail["outline_history"]
    assert detail["research_report"]["audience"]
    assert detail["research_report"]["page_focus"]

def test_requirements_analysis_should_publish_before_outline(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Requirements Stage",
            "project_id": "p-req",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    req_start = next(item for item in detail["events"] if item["event"] == "requirements.analyzing.started")
    req_done = next(item for item in detail["events"] if item["event"] == "requirements.analyzing.completed")
    req_event = next(item for item in detail["events"] if item["event"] == "requirements.analyzed")
    outline_event = next(item for item in detail["events"] if item["event"] == "outline.completed")
    assert req_start["seq"] < req_done["seq"] < outline_event["seq"]
    assert req_event["seq"] >= req_done["seq"]
    report = detail["research_report"]
    assert report["page_count_fixed"] == 3
    assert report["content_source_mode"] == "rag_first"
    assert report["effective_template_style"]

def test_confirm_gate_and_scratch_success_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=SlowMockLLMClient())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Data Platform",
            "project_id": "p2",
            "rag_source_ids": ["a", "b", "c"],
            "template_style": "business",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]

    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 409
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 200
    final_data = wait_status(client, run_id, {"SUCCEEDED"})

    assert final_data["compile_js_path"] and Path(final_data["compile_js_path"]).exists()
    assert final_data["pptx_path"] in {None, ""}
    assert len(final_data["slides"]) == 4
    assert all(item.get("js_path") and Path(item["js_path"]).exists() for item in final_data["slides"])
    assert final_data["qa_report"]["passed"] is True
    assert final_data["generation_result"]["compile_bundle_ready"] is True
    assert final_data["compile_bundle"]["status"] == "ready"
    assert final_data["compile_bundle"]["provider"] == "diego"
    assert final_data["compile_bundle"]["entrypoint"] == "slides/compile.js"
    assert final_data["compile_bundle"]["build_endpoint"] == f"/v1/ppt/runs/{run_id}/artifacts/compile-bundle"
    assert final_data["compile_result"]["status"] == "bundle_ready"
    assert final_data["compile_result"]["requested_provider"] == "none"
    compile_event = next(item for item in final_data["events"] if item["event"] == "compile.completed")
    assert compile_event["payload"]["bundle_ready"] is True
    assert compile_event["payload"]["deferred"] is True


def test_run_detail_and_download_should_expose_pptx_before_succeeded_guard(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))
    client.__enter__()

    pptx_path = tmp_path / "artifacts" / "manual-ready.pptx"
    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    pptx_path.write_bytes(b"manual-pptx")
    run = RunRecord(
        run_id="r-manual-ready",
        trace_id="t-manual-ready",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(topic="Manual Ready", project_id="p-manual"),
        artifact_dir=str(tmp_path / "artifacts" / "r-manual-ready"),
        pptx_path=str(pptx_path),
    )
    asyncio.run(orch.store.add_run(run))

    detail = client.get("/v1/ppt/runs/r-manual-ready")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["pptx_ready"] is True
    assert payload["artifacts"]["pptx"]["downloadable"] is True

    download = client.get("/v1/ppt/runs/r-manual-ready/artifacts/pptx")
    assert download.status_code == 200
    assert download.content == b"manual-pptx"

def test_scratch_compile_can_use_pagevra_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None, content: bytes = b"") -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.content = content

        def json(self) -> dict:
            return dict(self._payload)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict | None = None):
            assert url == "http://pagevra.test/compile/bundles"
            assert json is not None
            assert json["provider"] == "diego"
            assert json["mode"] == "scratch"
            assert json["entrypoint"] == "slides/compile.js"
            assert any(item["path"] == "slides/compile.js" for item in json["files"])
            return FakeResponse(200, {"state": "success", "job_id": "job-pv-1"})

        async def get(self, url: str):
            assert url == "http://pagevra.test/compile/jobs/job-pv-1/artifacts/pptx"
            return FakeResponse(200, content=b"pagevra-pptx")

    monkeypatch.setattr(compile_engine_mod.httpx, "AsyncClient", FakeAsyncClient)
    client = make_client(
        tmp_path,
        compile_provider="pagevra",
        pagevra_base_url="http://pagevra.test",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Pagevra Compile",
            "project_id": "p-pagevra",
            "rag_source_ids": ["a", "b"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    assert Path(final["pptx_path"]).read_bytes() == b"pagevra-pptx"
    assert final["compile_provider"] == "pagevra"
    assert final["compile_fallback_used"] is False
    compile_event = next(item for item in final["events"] if item["event"] == "compile.completed")
    assert compile_event["payload"]["provider"] == "pagevra"
    assert compile_event["payload"]["requested_provider"] == "pagevra"
    assert compile_event["payload"]["fallback_used"] is False

def test_scratch_compile_local_provider_is_explicit_and_succeeds(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        compile_provider="local",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Local Compile",
            "project_id": "p-local",
            "rag_source_ids": ["a"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    assert Path(final["pptx_path"]).exists()
    assert final["compile_provider"] == "local"
    assert final["compile_fallback_used"] is False
    assert final["compile_bundle"]["available"] is True
    assert final["compile_bundle"]["provider"] == "diego"
    assert final["compile_result"]["status"] == "succeeded"
    compile_event = next(item for item in final["events"] if item["event"] == "compile.completed")
    assert compile_event["payload"]["provider"] == "local"
    assert compile_event["payload"]["requested_provider"] == "local"
    assert compile_event["payload"]["fallback_used"] is False


def test_scratch_compile_pagevra_should_fail_with_compile_stage_diagnostics_when_base_url_missing(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        compile_provider="pagevra",
        pagevra_base_url="",
    )
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Pagevra Missing URL",
            "project_id": "p-pagevra-missing",
            "rag_source_ids": ["a"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})

    assert final["failed_stage"] == "COMPILING"
    assert final["error_code"] == "PAGEVRA_BASE_URL_MISSING"
    assert final["error_details"]["provider"] == "pagevra"
    assert final["error_details"]["reason"] == "pagevra_base_url_missing"

def test_build_compile_bundle_returns_high_fidelity_scratch_manifest(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Compile Bundle",
            "project_id": "p-bundle",
            "rag_source_ids": ["a", "b"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    bundle = asyncio.run(orch.build_compile_bundle(run_id))
    assert bundle["provider"] == "diego"
    assert bundle["mode"] == "scratch"
    assert bundle["entrypoint"] == "slides/compile.js"
    assert bundle["compile_options"]["cwd"] == "slides"
    assert any(item["path"] == "slides/compile.js" for item in bundle["files"])

    api_bundle = client.get(f"/v1/ppt/runs/{run_id}/artifacts/compile-bundle")
    assert api_bundle.status_code == 200
    assert api_bundle.json()["entrypoint"] == "slides/compile.js"

def test_outline_update_then_approve_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Editable Outline",
            "project_id": "p-edit",
            "rag_source_ids": ["c1", "c2"],
            "template_style": "business",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    drafted = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    base_version = drafted["outline"]["version"]

    edited_outline = OutlineDocument(
        version=base_version,
        summary="edited summary",
        nodes=[
            OutlineNode(title="封面", bullets=["主题导入"], page_type="cover", layout_hint="cover-asymmetric"),
            OutlineNode(title="目录", bullets=["问题", "方法", "结果"], page_type="toc", layout_hint="toc-list"),
            OutlineNode(title="总结", bullets=["结论", "行动项"], page_type="summary", layout_hint="summary-cta"),
        ],
    ).model_dump(mode="json")

    update_resp = client.post(
        f"/v1/ppt/runs/{run_id}/outline/confirm",
        json={
            "approved": False,
            "outline": edited_outline,
            "base_version": base_version,
            "change_reason": "用户修改结构",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "AWAITING_OUTLINE_CONFIRM"

    detail_after_update = client.get(f"/v1/ppt/runs/{run_id}").json()
    assert detail_after_update["outline"]["version"] == base_version + 1
    assert detail_after_update["outline_history"][-1]["action"] == "updated"

    approve_resp = client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    assert approve_resp.status_code == 200
    final_data = wait_status(client, run_id, {"SUCCEEDED"})
    assert len(final_data["slides"]) == 3
    assert final_data["qa_report"]["passed"] is True

def test_outline_update_with_wrong_base_version_should_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Version Check",
            "project_id": "p-version",
            "rag_source_ids": ["s1"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    drafted = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    outline = drafted["outline"]
    resp = client.post(
        f"/v1/ppt/runs/{run_id}/outline/confirm",
        json={
            "approved": False,
            "outline": outline,
            "base_version": outline["version"] + 10,
            "change_reason": "wrong version",
        },
    )
    assert resp.status_code == 409

def test_scratch_chart_truth_report_should_use_qualitative_fallback_without_verified_numbers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "No Numeric Facts",
            "project_id": "p-chart-fallback",
            "rag_source_ids": ["c1", "c2"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    chart_report = final["chart_truth_report"]
    assert chart_report["slides"]
    assert all(item["has_verified_data"] is False for item in chart_report["slides"])
    assert all(item["mode"] == "qualitative_fallback" for item in chart_report["slides"])

def test_requirements_report_should_include_design_intent_payload(tmp_path: Path) -> None:
    class DesignIntentMockLLM(MockLLMClient):
        async def generate_design_intent(self, **kwargs):
            return {
                "palette_name": "Pure Tech Blue",
                "style_recipe": "sharp",
                "title_font": "Cambria",
                "body_font": "Calibri",
                "visual_strategy": "high contrast data-first",
                "density": "medium",
                "rationale": "align with technical audience",
            }

    settings = make_settings()
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=DesignIntentMockLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Design Intent Check",
            "project_id": "p-design-intent",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})

    report = detail["research_report"]
    assert report["design_intent"]["palette_name"] == "Pure Tech Blue"
    assert report["design_intent"]["style_recipe"] == "sharp"
    req_events = [item for item in detail["events"] if item["event"] == "requirements.analyzing.completed"]
    assert req_events
    assert req_events[-1]["payload"]["palette_name"] == "Pure Tech Blue"
    assert req_events[-1]["payload"]["style_recipe"] == "sharp"
