from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from os.path import commonpath
from pathlib import Path
import re
from typing import Callable, Sequence


RunSubprocess = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PptdRuntimeResult:
    ok: bool
    reason: str
    return_code: int | None
    stdout: str = ""
    stderr: str = ""
    output_path: Path | None = None
    output_dir: Path | None = None
    error_count: int | None = None
    warning_count: int | None = None


class PptdRuntimeAdapter:
    def __init__(
        self,
        *,
        skill_dir: Path,
        runner_image: str,
        run_subprocess: RunSubprocess = subprocess.run,
        platform: str = "linux/amd64",
        timeout_sec: float = 1200.0,
        runner_mode: str = "docker",
    ) -> None:
        self.skill_dir = Path(skill_dir)
        self.runner_image = runner_image
        self.run_subprocess = run_subprocess
        self.platform = platform
        self.timeout_sec = timeout_sec
        self.runner_mode = runner_mode

    def check(self, pptd_path: Path) -> PptdRuntimeResult:
        pptd_path = Path(pptd_path)
        work_dir = self._work_root([pptd_path])
        script_path = str(pptd_path) if self.runner_mode == "local" else self._work_path(pptd_path, work_dir)
        result = self._run(
            ["bash", "scripts/check.sh", script_path],
            work_dir=work_dir,
        )
        if not result.ok:
            return result
        summary = self._check_summary(result.stdout, result.stderr)
        if summary["warning_count"] and summary["warning_count"] > 0:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_check_warnings",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error_count=summary["error_count"],
                warning_count=summary["warning_count"],
            )
        if result.return_code != 0:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_check_failed",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                error_count=summary["error_count"],
                warning_count=summary["warning_count"],
            )
        return PptdRuntimeResult(
            ok=True,
            reason="",
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            error_count=summary["error_count"],
            warning_count=summary["warning_count"],
        )

    def convert(self, pptd_path: Path, *, output_path: Path) -> PptdRuntimeResult:
        pptd_path = Path(pptd_path)
        output_path = Path(output_path)
        work_dir = self._work_root([pptd_path, output_path])
        script_pptd_path = str(pptd_path) if self.runner_mode == "local" else self._work_path(pptd_path, work_dir)
        script_output_path = str(output_path) if self.runner_mode == "local" else self._work_path(output_path, work_dir)
        result = self._run(
            [
                "bash",
                "scripts/convert.sh",
                script_pptd_path,
                "-o",
                script_output_path,
            ],
            work_dir=work_dir,
        )
        if not result.ok:
            return result
        if result.return_code != 0:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_convert_failed",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                output_path=output_path,
            )
        if not output_path.exists():
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_convert_output_missing",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                output_path=output_path,
            )
        return PptdRuntimeResult(
            ok=True,
            reason="",
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            output_path=output_path,
        )

    def screenshot(
        self,
        pptx_path: Path,
        *,
        output_dir: Path,
        pages: str = "all",
        dpi: int = 150,
    ) -> PptdRuntimeResult:
        pptx_path = Path(pptx_path)
        output_dir = Path(output_dir)
        work_dir = self._work_root([pptx_path, output_dir])
        script_pptx_path = (
            str(pptx_path)
            if self.runner_mode == "local"
            else self._work_path(pptx_path, work_dir)
        )
        script_output_dir = (
            str(output_dir)
            if self.runner_mode == "local"
            else self._work_path(output_dir, work_dir)
        )
        result = self._run(
            [
                "bash",
                "scripts/screenshot.sh",
                script_pptx_path,
                "--pages",
                pages,
                "--output",
                script_output_dir,
                "--dpi",
                str(dpi),
            ],
            work_dir=work_dir,
        )
        if not result.ok:
            return result
        if result.return_code != 0:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_screenshot_failed",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                output_dir=output_dir,
            )
        if not any(output_dir.glob("*.png")):
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_screenshot_output_missing",
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
                output_dir=output_dir,
            )
        return PptdRuntimeResult(
            ok=True,
            reason="",
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            output_dir=output_dir,
        )

    def _run(self, runtime_args: Sequence[str], *, work_dir: Path) -> PptdRuntimeResult:
        if self.runner_mode == "local":
            return self._run_local(runtime_args)
        command = self._docker_command(runtime_args, work_dir=work_dir)
        try:
            completed = self.run_subprocess(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_sec,
                check=False,
            )
        except FileNotFoundError as exc:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_runner_unavailable",
                return_code=None,
                stderr=str(exc),
            )
        except subprocess.TimeoutExpired as exc:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_runner_timeout",
                return_code=None,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
            )
        return PptdRuntimeResult(
            ok=True,
            reason="",
            return_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def _check_output_reports_zero_errors(self, stdout: str, stderr: str) -> bool:
        output = f"{stdout}\n{stderr}".lower()
        return "summary:" in output and (
            "0 errors" in output or "0 error(s)" in output
        )

    def _check_summary(self, stdout: str, stderr: str) -> dict[str, int | None]:
        output = f"{stdout}\n{stderr}"
        summary_line = ""
        for line in reversed(output.splitlines()):
            if "summary:" in line.lower():
                summary_line = line
                break
        if not summary_line:
            return {"error_count": None, "warning_count": None}
        error_match = re.search(r"(\d+)\s+error(?:\(s\)|s)?", summary_line, re.IGNORECASE)
        warning_match = re.search(
            r"(\d+)\s+warning(?:\(s\)|s)?",
            summary_line,
            re.IGNORECASE,
        )
        return {
            "error_count": int(error_match.group(1)) if error_match else None,
            "warning_count": int(warning_match.group(1)) if warning_match else None,
        }

    def _run_local(self, runtime_args: Sequence[str]) -> PptdRuntimeResult:
        try:
            with tempfile.TemporaryDirectory(prefix="pptd-runtime-") as temp_dir:
                skill_copy = Path(temp_dir) / "pptx-skill"
                shutil.copytree(self.skill_dir, skill_copy)
                for runtime_file in (skill_copy / "scripts" / "runtime").glob("*pptd"):
                    runtime_file.chmod(runtime_file.stat().st_mode | 0o111)
                completed = self.run_subprocess(
                    list(runtime_args),
                    cwd=skill_copy,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_sec,
                    check=False,
                )
        except FileNotFoundError as exc:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_runner_unavailable",
                return_code=None,
                stderr=str(exc),
            )
        except subprocess.TimeoutExpired as exc:
            return PptdRuntimeResult(
                ok=False,
                reason="pptd_runner_timeout",
                return_code=None,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
            )
        return PptdRuntimeResult(
            ok=True,
            reason="",
            return_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def _docker_command(self, runtime_args: Sequence[str], *, work_dir: Path) -> list[str]:
        script = " && ".join(
            [
                "cp -a /opt/pptx-skill /tmp/pptx-skill",
                "find /tmp/pptx-skill/scripts/runtime -maxdepth 1 -type f -name '*pptd' -exec chmod +x {} \\;",
                "cd /tmp/pptx-skill",
                " ".join(shlex.quote(part) for part in runtime_args),
            ]
        )
        return [
            "docker",
            "run",
            "--rm",
            "--platform",
            self.platform,
            "-v",
            f"{self.skill_dir}:/opt/pptx-skill:ro",
            "-v",
            f"{work_dir}:/work",
            "-w",
            "/tmp",
            self.runner_image,
            "bash",
            "-lc",
            script,
        ]

    def _work_path(self, path: Path, work_dir: Path) -> str:
        relative = Path(path).resolve().relative_to(work_dir.resolve()).as_posix()
        return f"/work/{relative}"

    def _work_root(self, paths: Sequence[Path]) -> Path:
        return Path(commonpath([str(Path(path).resolve().parent) for path in paths]))
