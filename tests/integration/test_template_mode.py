from tests.support.service_flow_shared import *  # noqa: F401,F403

def test_template_repair_uses_latest_template_candidate_not_outline_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = CaptureTemplateRepairLLM()
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm,
        settings=make_settings(),
    )

    call_counter = {"n": 0}

    async def flaky_markitdown_check(_pptx_path: Path):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return False, "forced template qa failure"
        return True, None

    monkeypatch.setattr(orch, "_markitdown_check", flaky_markitdown_check)
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    template_file = tmp_path / "template_repair.pptx"
    build_structured_template_pptx(template_file)
    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template_repair.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Repair Loop",
            "project_id": "p-template-repair",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["qa_report"]["passed"] is True
    assert len(llm.review_candidate_titles) >= 2
    assert any(title.startswith("TMP-1-") for title in llm.review_candidate_titles[1:])

def test_template_upload_and_template_generation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "template.pptx"
    build_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    detail = client.get(f"/v1/ppt/templates/{template_id}")
    assert detail.status_code == 200

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Run",
            "project_id": "p4",
            "rag_source_ids": ["x"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["artifacts"]["pptx"]["downloadable"] is True
    assert Path(final["artifacts"]["pptx"]["path"]).exists()
    assert final["slides"]
    assert all(item.get("js_path") and Path(item["js_path"]).exists() for item in final["slides"])
    assert final["qa_report"]["passed"] is True
    assert final["artifacts"]["pptx"]["downloadable"] is True
    assert final["compile_result"]["status"] == "not_requested"
    assert final["compile_result"]["requested_provider"] is None
    assert final["compile_result"]["provider"] is None
    assert final["compile_result"]["artifact_path"] is None
    compile_event = next(item for item in final["events"] if item["event"] == "compile.completed")
    assert compile_event["payload"]["requested_provider"] == "none"
    assert compile_event["payload"]["provider"] is None

def test_template_structural_rebuild_for_target_count(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "structured_template.pptx"
    build_structured_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("structured_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Rebuild",
            "project_id": "p5",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "business",
            "target_slide_count": 3,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    output_pptx = Path(final["artifacts"]["pptx"]["path"])
    assert output_pptx.exists()
    with ZipFile(output_pptx, "r") as zf:
        names = set(zf.namelist())
        assert "ppt/slides/slide1.xml" in names
        assert "ppt/slides/slide2.xml" in names
        assert "ppt/slides/slide3.xml" in names
        presentation_xml = zf.read("ppt/presentation.xml").decode("utf-8", errors="ignore")
        content_types_xml = zf.read("[Content_Types].xml").decode("utf-8", errors="ignore")

    assert presentation_xml.count("<p:sldId ") == 3
    assert "/ppt/slides/slide3.xml" in content_types_xml

def test_template_semantic_placeholder_replacement(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "semantic_template.pptx"
    build_semantic_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("semantic_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Semantic Template",
            "project_id": "p7",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "business",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    output_pptx = Path(final["artifacts"]["pptx"]["path"])
    assert output_pptx.exists()
    with ZipFile(output_pptx, "r") as zf:
        slide1_xml = zf.read("ppt/slides/slide1.xml").decode("utf-8", errors="ignore")
        chart_xml = zf.read("ppt/charts/chart1.xml").decode("utf-8", errors="ignore")
        slide1_rels = zf.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8", errors="ignore")

        rid2 = re.search(r'Id="rId2"[^>]*Target="([^"]+)"', slide1_rels)
        rid3 = re.search(r'Id="rId3"[^>]*Target="([^"]+)"', slide1_rels)
        assert rid2 and rid3
        media_target_1 = posixpath.normpath(f"ppt/slides/{rid2.group(1)}")
        media_target_2 = posixpath.normpath(f"ppt/slides/{rid3.group(1)}")
        media_bytes_1 = zf.read(media_target_1)
        media_bytes_2 = zf.read(media_target_2)

    assert "Template Placeholder" not in slide1_xml
    assert "placeholder cell" not in slide1_xml
    assert "caption placeholder" not in slide1_xml
    assert "Image Placeholder" not in slide1_xml
    assert "Chart Placeholder" not in chart_xml
    assert media_bytes_1.startswith(b"\x89PNG\r\n\x1a\n")
    assert media_bytes_2.startswith(b"\x89PNG\r\n\x1a\n")

def test_template_asset_provider_failure_should_hard_fail(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=Settings(
            llm_api_style="openai_chat",
            llm_base_url="https://api.example.com",
            llm_api_key="test",
            llm_model="test-model",
            llm_timeout_sec=30.0,
            llm_max_retries=2,
            llm_temperature_outline=0.3,
            llm_temperature_slide=0.6,
            slide_concurrency=2,
            slide_retry=2,
            qa_enabled=True,
            repair_rounds=2,
            asset_provider="unsplash",
            unsplash_access_key="",
            pexels_api_key="",
            asset_timeout_sec=3.0,
            asset_max_retries=1,
            generation_engine="agentic_v2",
            debug_keep_previews=False,
            max_slide_repair_rounds=2,
        ),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    template_file = tmp_path / "semantic_template_for_fail.pptx"
    build_semantic_template_pptx(template_file)
    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("semantic_template_for_fail.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Asset Fail",
            "project_id": "p-asset-fail",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "TEMPLATE_ASSET_FETCH_FAILED"

def test_template_slot_mismatch_should_remove_excess_picture_groups(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "excess_slot_template.pptx"
    build_excess_slot_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("excess_slot_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Slot Trim",
            "project_id": "p-slot-trim",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    with ZipFile(final["artifacts"]["pptx"]["path"], "r") as zf:
        slide1_xml = zf.read("ppt/slides/slide1.xml").decode("utf-8", errors="ignore")
        slide1_rels = zf.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8", errors="ignore")

    assert slide1_xml.count("<p:pic") == 2
    assert 'Id="rId4"' not in slide1_rels

def test_template_invalid_should_fail_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def markitdown_fail_for_template(args, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        cmd = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
        if "markitdown" in cmd and "template.pptx" in cmd:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="template parse error")
        return fake_subprocess_run(args, cwd=cwd, capture_output=capture_output, text=text, check=check, **kwargs)

    monkeypatch.setattr(orchestrator_mod.subprocess, "run", markitdown_fail_for_template)
    client = make_client(tmp_path)
    template_file = tmp_path / "template_invalid.pptx"
    build_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template_invalid.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Invalid Template",
            "project_id": "p6",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "TEMPLATE_MARKITDOWN_FAILED"

def test_template_unknown_placeholder_should_fail_fast_with_mapping_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "unknown_slot_template.pptx"
    build_unknown_slot_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("unknown_slot_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Unknown Placeholder",
            "project_id": "p-unknown-slot",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})

    assert final["error_code"] == "TEMPLATE_SLOT_UNMAPPED"
    assert final["template_mapping_report"]["passed"] is False
    assert final["template_mapping_report"]["unmapped_required"]
    assert any(item.get("slot_type") == "unknown" for item in final["template_mapping_report"]["unmapped_required"])

def test_template_layout_conflict_should_fail_fast_with_layout_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "layout_conflict_template.pptx"
    build_layout_conflict_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("layout_conflict_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Layout Conflict",
            "project_id": "p-layout-conflict",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})

    assert final["error_code"] == "TEMPLATE_LAYOUT_CONFLICT"
    assert final["template_layout_report"]["slides"]
    slide_report = final["template_layout_report"]["slides"][0]
    assert slide_report["issues_after_count"] > 0
    assert slide_report["passed"] is False
