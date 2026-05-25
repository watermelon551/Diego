from __future__ import annotations

import subprocess
from pathlib import Path

from service.pptd_runtime import PptdRuntimeAdapter


def _write_minimal_project(project_dir: Path) -> Path:
    pages_dir = project_dir / "pages"
    pages_dir.mkdir(parents=True)
    pptd_path = project_dir / "deck.pptd"
    pptd_path.write_text(
        "\n".join(
            [
                "title: Adapter Smoke",
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                '    primary: "#2563eb"',
                '    background: "#ffffff"',
                '    text: "#111827"',
                "  textStyles:",
                "    title:",
                "      fontSize: 48",
                '      color: "$primary"',
                '      fontFamily: "MiSans"',
                "pages:",
                "  - pages/cover.page",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pages_dir / "cover.page").write_text(
        "\n".join(
            [
                "pageType: cover",
                "elements:",
                "  - elementId: title",
                "    elementType: text",
                "    bounds: [120, 220, 1040, 100]",
                "    content:",
                '      style: "$title"',
                "      text: |",
                "        Adapter Smoke",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pptd_path


def test_pptd_runtime_adapter_runs_check_and_convert_with_neutral_runner(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        if "convert.sh" in " ".join(args):
            (tmp_path / "project" / "deck.pptx").write_bytes(b"pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Checking deck.pptd\nSummary: 0 errors, 0 warnings",
            stderr="",
        )

    pptd_path = _write_minimal_project(tmp_path / "project")
    adapter = PptdRuntimeAdapter(
        skill_dir=tmp_path / "pptx-skill",
        runner_image="debian:bookworm-slim",
        run_subprocess=fake_run,
    )

    check = adapter.check(pptd_path)
    convert = adapter.convert(pptd_path, output_path=tmp_path / "project" / "deck.pptx")

    assert check.ok is True
    assert check.reason == ""
    assert convert.ok is True
    assert convert.output_path == tmp_path / "project" / "deck.pptx"
    assert len(calls) == 2
    assert all(call[:4] == ["docker", "run", "--rm", "--platform"] for call in calls)
    assert all("linux/amd64" in call for call in calls)
    assert "check.sh" in " ".join(calls[0])
    assert "convert.sh" in " ".join(calls[1])


def test_pptd_runtime_adapter_classifies_check_failure(tmp_path: Path) -> None:
    def fake_run(args, **_kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="Checking deck.pptd\nSummary: 1 errors, 0 warnings",
            stderr="TextOverflowWarning",
        )

    pptd_path = _write_minimal_project(tmp_path / "project")
    adapter = PptdRuntimeAdapter(
        skill_dir=tmp_path / "pptx-skill",
        runner_image="debian:bookworm-slim",
        run_subprocess=fake_run,
    )

    result = adapter.check(pptd_path)

    assert result.ok is False
    assert result.reason == "pptd_check_failed"
    assert result.return_code == 1
    assert "TextOverflowWarning" in result.stderr


def test_pptd_runtime_adapter_classifies_runner_unavailable(tmp_path: Path) -> None:
    def fake_run(_args, **_kwargs):
        raise FileNotFoundError("docker")

    pptd_path = _write_minimal_project(tmp_path / "project")
    adapter = PptdRuntimeAdapter(
        skill_dir=tmp_path / "pptx-skill",
        runner_image="debian:bookworm-slim",
        run_subprocess=fake_run,
    )

    result = adapter.check(pptd_path)

    assert result.ok is False
    assert result.reason == "pptd_runner_unavailable"
    assert result.return_code is None


def test_pptd_runtime_adapter_can_write_output_outside_pptd_project(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        (tmp_path / "slides" / "output" / "presentation.pptx").parent.mkdir()
        (tmp_path / "slides" / "output" / "presentation.pptx").write_bytes(b"pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")

    pptd_path = _write_minimal_project(tmp_path / "slides" / "pptd")
    output_path = tmp_path / "slides" / "output" / "presentation.pptx"
    adapter = PptdRuntimeAdapter(
        skill_dir=tmp_path / "pptx-skill",
        runner_image="debian:bookworm-slim",
        run_subprocess=fake_run,
    )

    result = adapter.convert(pptd_path, output_path=output_path)

    assert result.ok is True
    assert result.output_path == output_path
    command = " ".join(calls[0])
    assert "/work/pptd/deck.pptd" in command
    assert "/work/output/presentation.pptx" in command
