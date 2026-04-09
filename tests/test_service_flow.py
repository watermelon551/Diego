from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

import service.orchestrator as orchestrator_mod
from service.app import create_app
from service.config import Settings, load_settings
from service.llm_client import MockLLMClient
from service.models import OutlineDocument, OutlineNode
from service.orchestrator import RunOrchestrator
from service.store import RunStore


class SlowMockLLMClient(MockLLMClient):
    async def generate_outline(self, **kwargs):
        await asyncio.sleep(0.05)
        return await super().generate_outline(**kwargs)


def fake_subprocess_run(args, cwd=None, capture_output=False, text=False, check=False, **kwargs):
    cmd = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
    if "node" in cmd and "compile.js" in cmd:
        out = Path(cwd) / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "presentation.pptx").write_bytes(b"fake-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="compiled", stderr="")
    if "python" in cmd and "markitdown" in cmd:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="slide content extracted", stderr="")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def make_settings() -> Settings:
    return Settings(
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
    )


def make_client(tmp_path: Path, llm_client: MockLLMClient | None = None) -> TestClient:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm_client or MockLLMClient(),
        settings=make_settings(),
    )
    return TestClient(create_app(base_dir=tmp_path, orchestrator=orch))


def wait_status(client: TestClient, run_id: str, expected: set[str], timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/v1/ppt/runs/{run_id}").json()
        if data["status"] in expected:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} not in {expected} within {timeout}s")


def build_template_pptx(path: Path) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>")
        zf.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><a:t>Template Placeholder</a:t></p:sld>")


def build_structured_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>
"""
    slide_tpl = "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{text}</a:t></a:r></a:p><a:p><a:r><a:t>old bullet</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_tpl.format(text="Template Slide 1"))
        zf.writestr("ppt/slides/slide2.xml", slide_tpl.format(text="Template Slide 2"))


@pytest.fixture(autouse=True)
def patch_tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(orchestrator_mod.subprocess, "run", fake_subprocess_run)
    yield


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

    assert final_data["pptx_path"] and Path(final_data["pptx_path"]).exists()
    assert final_data["compile_js_path"] and Path(final_data["compile_js_path"]).exists()
    assert len(final_data["slides"]) == 4
    assert all(item.get("js_path") and Path(item["js_path"]).exists() for item in final_data["slides"])
    assert final_data["qa_report"]["passed"] is True


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
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    with client.stream("GET", f"/v1/ppt/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())

    assert "event: outline.token" in body
    assert "event: outline.completed" in body
    assert "event: plan.completed" in body
    assert "event: slide.generated" in body
    assert "event: qa.completed" in body


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
    assert final["pptx_path"] and Path(final["pptx_path"]).exists()
    assert final["qa_report"]["passed"] is True


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

    output_pptx = Path(final["pptx_path"])
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
