from __future__ import annotations

from service.run.slide_scene import apply_scene_operations, build_slide_scene


def _sample_slide_js() -> str:
    return "\n".join(
        [
            "const slideConfig = {",
            "  type: 'content',",
            "  index: 1,",
            "  title: 'Initial Title',",
            "  bullets: ['Alpha', 'Beta'],",
            "};",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
            "  slide.addText(slideConfig.title, { x: 0.5, y: 0.4, w: 9.0, h: 0.8, fontSize: 40, color: theme.primary, bold: true });",
            "  slide.addImage({ path: 'https://example.com/old.png', x: 6.8, y: 1.5, w: 2.2, h: 1.6 });",
            "  slide.addText(rows, { x: 1.1, y: 1.9, w: 7.8, h: 2.7, fontSize: 16, color: theme.secondary, align: 'left' });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )


def test_build_slide_scene_extracts_text_and_image_nodes() -> None:
    parsed = build_slide_scene(js_code=_sample_slide_js(), run_id="run-1", slide_no=1)

    assert parsed.scene.slide_id == "run-1-slide-0"
    assert parsed.scene.readonly is False
    assert [node.node_id for node in parsed.scene.nodes] == [
        "text:config:title",
        "image:call:1",
        "text:config:bullets",
    ]
    assert parsed.scene.nodes[0].text == "Initial Title"
    assert parsed.scene.nodes[1].src == "https://example.com/old.png"
    assert parsed.scene.nodes[2].text == "Alpha\nBeta"


def test_apply_scene_operations_updates_scene_version_and_values() -> None:
    original = _sample_slide_js()
    parsed = build_slide_scene(js_code=original, run_id="run-1", slide_no=1)

    updated_js, updated = apply_scene_operations(
        js_code=original,
        parsed_scene=parsed,
        scene_version=parsed.scene.scene_version,
        operations=[
            {"op": "replace_text", "node_id": "text:config:title", "value": "Updated Title"},
            {"op": "replace_text", "node_id": "text:config:bullets", "value": "One\nTwo\nThree"},
            {"op": "replace_image", "node_id": "image:call:1", "value": "https://example.com/new.png"},
        ],
        run_id="run-1",
        slide_no=1,
    )

    assert "Updated Title" in updated_js
    assert "https://example.com/new.png" in updated_js
    assert '["One", "Two", "Three"]' in updated_js
    assert updated.scene.scene_version != parsed.scene.scene_version
    assert updated.scene.nodes[0].text == "Updated Title"
    assert updated.scene.nodes[1].src == "https://example.com/new.png"
    assert updated.scene.nodes[2].text == "One\nTwo\nThree"
