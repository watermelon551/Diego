from __future__ import annotations

from pathlib import Path

import pytest

from service.run.slide_preview import render_slide_via_pagevra


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, _url: str, json: dict) -> _FakeResponse:
        assert _url.endswith("/compile/bundles")
        assert json["mode"] == "single_slide"
        assert json["entrypoint"] == "slides/slide1.js"
        assert json["metadata"]["compile_context"]["theme"]["accent"] == "123456"
        return _FakeResponse(200, self._payload)


@pytest.mark.anyio
async def test_render_slide_via_pagevra_requires_svg_compile_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slide_js_path = tmp_path / "slide1.js"
    slide_js_path.write_text("module.exports = { createSlide: () => undefined };\n", encoding="utf-8")
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(
            payload={
                "state": "success",
                "job_id": "compile-1",
                "artifacts": {
                    "preview_pages": [
                        {
                            "index": 0,
                            "slide_id": "slide-01",
                            "format": "svg",
                            "svg_data_url": "data:image/svg+xml;base64,preview",
                            "width": 960,
                            "height": 540,
                        }
                    ]
                },
            }
        ),
    )

    result = await render_slide_via_pagevra(
        slide_js_path=slide_js_path,
        theme={"accent": "#123456", "bg": "#ffffff", "secondary": "#111111"},
        slide_no=1,
        pagevra_base_url="http://pagevra.test",
    )

    assert result["preview_format"] == "svg"
    assert result["svg_data_url"] == "data:image/svg+xml;base64,preview"
    assert result["preview"]["format"] == "svg"
    assert result["width"] == 960
    assert result["height"] == 540
    assert result["pagevra_job_id"] == "compile-1"
