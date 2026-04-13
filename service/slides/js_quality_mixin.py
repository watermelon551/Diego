from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..models import EventType, GenerationMode, OutlineNode, SlidePageType, VisualPolicy
from ..run.types import JsLayoutBox, SLIDE_HEIGHT_IN, SLIDE_WIDTH_IN
from .js_asset_contract import collect_addimage_signature_issues, collect_addshape_signature_issues, collect_addtext_signature_issues, collect_detected_api_violations, canonicalize_addimage_signature, extract_main_asset_path, extract_planned_asset_paths, has_image_placeholder_text


class SlideJsQualityMixin:
    def _normalize_generated_slide_js(
        self,
        js_code: str,
        *,
        slide_no: int,
        node: OutlineNode,
        target_slide_count: int,
    ) -> tuple[str, list[str]]:
        normalized = str(js_code or "")
        fixes: list[str] = []

        def _replace_text(old: str, new: str, label: str) -> None:
            nonlocal normalized
            if old in normalized:
                normalized = normalized.replace(old, new)
                fixes.append(label)

        def _replace_regex(pattern: str, repl: Any, label: str, *, flags: int = 0) -> None:
            nonlocal normalized
            updated, count = re.subn(pattern, repl, normalized, flags=flags)
            if count > 0:
                normalized = updated
                fixes.append(label)

        # Strip accidental markdown wrappers.
        _replace_regex(r"(?m)^```(?:javascript|js)?\s*$", "", "strip markdown fence header")
        _replace_regex(r"(?m)^```\s*$", "", "strip markdown fence footer")
        normalized = normalized.strip() + "\n"

        # Normalize common wrong require/module names.
        _replace_text("require('pptxgengen')", "require('pptxgenjs')", "fix require(pptxgenjs) single quote")
        _replace_text('require("pptxgengen")', 'require("pptxgenjs")', "fix require(pptxgenjs) double quote")

        # Normalize createSlide signature and async misuse.
        _replace_regex(
            r"\basync\s+function\s+createSlide\s*\(\s*pres\s*,\s*theme\s*\)",
            "function createSlide(pres, theme)",
            "remove async createSlide",
        )

        # background API: slide.background({...}) -> slide.background = {...}
        def _background_call_to_assignment(match: re.Match[str]) -> str:
            return f"{match.group(1)}.background = {match.group(2)};"

        _replace_regex(
            r"(?ms)^(\s*[A-Za-z_][A-Za-z0-9_]*)\.background\(\s*(\{.*?\})\s*\)\s*;",
            _background_call_to_assignment,
            "normalize background({...}) call",
        )
        _replace_regex(
            r"(?m)^(\s*slide)\.background\(\s*theme\.bg\s*\)\s*;",
            r"\1.background = { color: theme.bg };",
            "normalize background(theme.bg) call",
        )
        _replace_regex(
            r"(?m)^(\s*slide)\.background\s*=\s*theme\.bg\s*;",
            r"\1.background = { color: theme.bg };",
            "normalize background assignment",
        )

        # Normalize enum namespaces to legal pptxgenjs usage.
        _replace_text("pres.ShapeType.", "pres.shapes.", "normalize ShapeType namespace")
        _replace_regex(r"\bShapeType\.", "pres.shapes.", "normalize ShapeType token")
        _replace_regex(r"\bslide\.shapes\.", "pres.shapes.", "normalize slide.shapes namespace")
        _replace_regex(r"\b(?:pptxgen|pptx)\.shapes\.", "pres.shapes.", "normalize global shapes namespace")
        _replace_regex(
            r"addShape\(\s*[A-Za-z_][A-Za-z0-9_]*\.shapes\.",
            "addShape(pres.shapes.",
            "normalize addShape enum namespace",
        )
        _replace_regex(r"pres\.shapes\.ELLIPSE\b", "pres.shapes.OVAL", "replace ELLIPSE with OVAL")
        _replace_regex(r"pres\.shapes\.RT_TRIANGLE\b", "pres.shapes.RIGHT_TRIANGLE", "replace RT_TRIANGLE with RIGHT_TRIANGLE")

        # fit API: pres.Fit.shrink -> 'shrink'
        _replace_regex(r"\b[A-Za-z_][A-Za-z0-9_]*\.Fit\.[sS]hrink\b", "'shrink'", "normalize Fit.shrink")
        _replace_regex(r"\bpres\.utilitextfit\([^)]*\)", "36", "replace unsupported pres.utilitextfit")

        # addShape('rect', ...) -> addShape(pres.shapes.RECTANGLE, ...)
        shape_alias = {
            "rect": "RECTANGLE",
            "rectangle": "RECTANGLE",
            "rounded_rectangle": "ROUNDED_RECTANGLE",
            "roundedrectangle": "ROUNDED_RECTANGLE",
            "roundrect": "ROUNDED_RECTANGLE",
            "oval": "OVAL",
            "ellipse": "OVAL",
            "circle": "OVAL",
            "line": "LINE",
            "triangle": "RIGHT_TRIANGLE",
            "rt_triangle": "RIGHT_TRIANGLE",
            "right_triangle": "RIGHT_TRIANGLE",
            "diamond": "DIAMOND",
            "chevron": "CHEVRON",
            "hexagon": "HEXAGON",
            "parallelogram": "PARALLELOGRAM",
            "pentagon": "PENTAGON",
            "pie": "PIE",
        }

        def _shape_literal_repl(match: re.Match[str]) -> str:
            token = (match.group(1) or "").strip()
            mapped = shape_alias.get(token.lower(), token.upper())
            return f"addShape(pres.shapes.{mapped}"

        _replace_regex(
            r"addShape\(\s*['\"]([A-Za-z0-9_\-]+)['\"]",
            _shape_literal_repl,
            "normalize addShape string literal",
        )

        # normalize lower-case pres.shapes.rect -> pres.shapes.RECTANGLE
        def _shape_enum_case_repl(match: re.Match[str]) -> str:
            token = match.group(1)
            mapped = shape_alias.get(token.lower(), token.upper())
            return f"pres.shapes.{mapped}"

        _replace_regex(
            r"pres\.shapes\.([A-Za-z_][A-Za-z0-9_]*)",
            _shape_enum_case_repl,
            "normalize pres.shapes token case",
        )

        # slide.addPageBadge(...) is invalid, convert to helper call.
        _replace_regex(
            r"(?m)^\s*slide\.addPageBadge\((.*?)\)\s*;",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "replace invalid slide.addPageBadge call",
        )

        # Inject addPageBadge helper if used but missing.
        if "addPageBadge(" in normalized and "function addPageBadge(" not in normalized:
            fixes.append("inject addPageBadge helper")
            badge_helper = "\n".join(
                [
                    "function addPageBadge(pres, slide, theme, n) {",
                    "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "}",
                    "",
                ]
            )
            if "function createSlide(" in normalized:
                normalized = normalized.replace("function createSlide(", badge_helper + "function createSlide(", 1)
            else:
                normalized = badge_helper + normalized

        # LINE shape with zero width/height causes compile failures in pptxgenjs.
        _replace_regex(
            r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bw\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))",
            r"\g<1>0.01",
            "fix LINE shape zero width",
            flags=re.S,
        )
        _replace_regex(
            r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bh\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))",
            r"\g<1>0.01",
            "fix LINE shape zero height",
            flags=re.S,
        )

        # Normalize some common invalid export forms.
        _replace_regex(
            r"module\.exports\s*=\s*createSlide\s*;",
            "module.exports = { createSlide, slideConfig };",
            "normalize module.exports short form",
        )
        _replace_regex(
            r"module\.exports\s*=\s*\{\s*createSlide\s*\}\s*;",
            "module.exports = { createSlide, slideConfig };",
            "normalize module.exports object form",
        )

        if "module.exports = { createSlide, slideConfig };" in normalized and not re.search(
            r"\b(?:const|let|var)\s+slideConfig\b",
            normalized,
        ):
            fixes.append("inject missing slideConfig object")
            slide_config_fallback = "\n".join(
                [
                    "const slideConfig = {",
                    f"  type: {json.dumps(node.page_type.value)},",
                    f"  index: {slide_no},",
                    f"  total: {target_slide_count},",
                    f"  title: {json.dumps(node.title, ensure_ascii=False)},",
                    f"  layoutHint: {json.dumps(node.layout_hint or 'content-two-column')},",
                    f"  bullets: {json.dumps(node.bullets or [node.title], ensure_ascii=False)},",
                    "};",
                    "",
                ]
            )
            if "const pptxgen" in normalized:
                normalized = normalized.replace("const pptxgen = require('pptxgenjs');", "const pptxgen = require('pptxgenjs');\n" + slide_config_fallback, 1)
            else:
                normalized = slide_config_fallback + normalized

        # Ensure module export exists when createSlide + slideConfig are present.
        if "module.exports" not in normalized and "function createSlide" in normalized and "slideConfig" in normalized:
            fixes.append("append module.exports contract")
            normalized = normalized.rstrip() + "\n\nmodule.exports = { createSlide, slideConfig };\n"

        return normalized, self._dedupe_preserve_order(fixes)

    def _auto_canonicalize_slide_js(
        self,
        js_code: str,
        *,
        slide_no: int,
        node: OutlineNode,
        target_slide_count: int,
    ) -> tuple[str, list[str]]:
        canonical = str(js_code or "")
        fixes: list[str] = []

        # Repair addGroup misuse by flattening group API calls onto slide.
        group_vars = re.findall(r"(?m)^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*slide\.addGroup\(\s*\)\s*;", canonical)
        if group_vars:
            canonical = re.sub(
                r"(?m)^\s*(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*slide\.addGroup\(\s*\)\s*;\s*$",
                "",
                canonical,
            )
            for var_name in group_vars:
                canonical = re.sub(rf"\b{re.escape(var_name)}\.(add(?:Shape|Text|Image|Chart))\(", r"slide.\1(", canonical)
            fixes.append("flatten slide.addGroup() usage")

        legal_shapes = {
            str(item).strip().upper()
            for item in (self._js_api_contract.get("legal_shape_enum", []) or [])
            if str(item).strip()
        }
        if legal_shapes:
            replaced_unknown_shape = False

            def _shape_guard(match: re.Match[str]) -> str:
                nonlocal replaced_unknown_shape
                token = str(match.group(1) or "").upper()
                if token in legal_shapes:
                    return f"pres.shapes.{token}"
                replaced_unknown_shape = True
                return "pres.shapes.RECTANGLE"

            canonical = re.sub(r"pres\.shapes\.([A-Z][A-Z0-9_]+)", _shape_guard, canonical)
            if replaced_unknown_shape:
                fixes.append("replace unknown shape enum with RECTANGLE")

        # Fix rare malformed export line where trailing comma breaks Node parse.
        updated, count = re.subn(
            r"module\.exports\s*=\s*\{\s*createSlide\s*,\s*slideConfig\s*,\s*\}\s*;",
            "module.exports = { createSlide, slideConfig };",
            canonical,
        )
        if count > 0:
            canonical = updated
            fixes.append("fix malformed module.exports trailing comma")

        canonical, addimage_fix_count = canonicalize_addimage_signature(
            canonical,
            split_top_level_args=self._split_top_level_args,
            find_matching_delimiter=lambda payload, start_idx, open_char, close_char: self._find_matching_delimiter(
                payload,
                start_idx=start_idx,
                open_char=open_char,
                close_char=close_char,
            ),
        )
        if addimage_fix_count > 0:
            fixes.append("normalize addImage(path, opts) to addImage({ path, ...opts })")

        # Ensure minimal slideConfig exists if still missing but exported.
        if "module.exports = { createSlide, slideConfig };" in canonical and not re.search(
            r"\b(?:const|let|var)\s+slideConfig\b",
            canonical,
        ):
            fallback = "\n".join(
                [
                    "const slideConfig = {",
                    f"  type: {json.dumps(node.page_type.value)},",
                    f"  index: {slide_no},",
                    f"  total: {target_slide_count},",
                    f"  title: {json.dumps(node.title, ensure_ascii=False)},",
                    f"  layoutHint: {json.dumps(node.layout_hint or 'content-two-column')},",
                    f"  bullets: {json.dumps(node.bullets or [node.title], ensure_ascii=False)},",
                    "};",
                    "",
                ]
            )
            if "const pptxgen" in canonical:
                canonical = canonical.replace("const pptxgen = require('pptxgenjs');", "const pptxgen = require('pptxgenjs');\n" + fallback, 1)
            else:
                canonical = fallback + canonical
            fixes.append("inject minimal slideConfig fallback")

        return canonical, self._dedupe_preserve_order(fixes)

    def _truncate_diag_text(self, text: str, *, limit: int | None = None) -> str:
        payload = str(text or "")
        max_chars = max(256, int(limit if limit is not None else self.slide_diag_max_stderr_chars))
        if len(payload) <= max_chars:
            return payload
        return payload[:max_chars] + f"\n...[truncated {len(payload) - max_chars} chars]"

    def _render_js_with_line_numbers(self, js_code: str) -> str:
        lines = str(js_code or "").splitlines()
        max_lines = max(40, self.slide_diag_max_js_lines)
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... [truncated {len(str(js_code or '').splitlines()) - max_lines} lines]"]
        return "\n".join(f"{idx + 1:04d}| {line}" for idx, line in enumerate(lines))

    def _extract_line_numbers(self, text: str) -> list[int]:
        line_numbers: list[int] = []
        for match in re.finditer(r":(\d+)(?::\d+)?\b", str(text or "")):
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if value > 0:
                line_numbers.append(value)
        seen: set[int] = set()
        deduped: list[int] = []
        for item in line_numbers:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped[:8]

    def _extract_js_focus_windows(self, js_code: str, *, line_numbers: list[int], radius: int = 4) -> list[dict[str, Any]]:
        lines = str(js_code or "").splitlines()
        if not lines:
            return []
        windows: list[dict[str, Any]] = []
        for line_no in line_numbers[:6]:
            idx = max(1, line_no)
            start = max(1, idx - radius)
            end = min(len(lines), idx + radius)
            snippet = "\n".join(f"{n:04d}| {lines[n - 1]}" for n in range(start, end + 1))
            windows.append({"line": idx, "start": start, "end": end, "snippet": snippet})
        return windows[:4]

    def _build_slide_failure_context(
        self,
        *,
        phase: str,
        slide_js_path: Path | None,
        candidate_js: str,
        issues: list[str],
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diag = dict(diagnostics or {})
        stdout = self._truncate_diag_text(str(diag.get("stdout", "")))
        stderr = self._truncate_diag_text(str(diag.get("stderr", "")))
        command = str(diag.get("command", ""))
        exit_code = diag.get("exit_code")
        error_class = str(diag.get("error_class", ""))
        error_message = self._truncate_diag_text(str(diag.get("error_message", "")))
        numbered = self._render_js_with_line_numbers(candidate_js)
        line_numbers = self._extract_line_numbers("\n".join([stderr, stdout, error_message, "\n".join(issues or [])]))
        focus = self._extract_js_focus_windows(candidate_js, line_numbers=line_numbers)
        first_line = line_numbers[0] if line_numbers else None
        error_location = {"line": first_line} if first_line else {}
        gate_summary = diag.get("gate_summary") if isinstance(diag.get("gate_summary"), dict) else {}
        context = {
            "phase": phase,
            "slide_js": slide_js_path.name if slide_js_path else "",
            "slide_js_path": str(slide_js_path) if slide_js_path else "",
            "issues": self._dedupe_preserve_order([str(item) for item in (issues or []) if str(item).strip()])[:24],
            "command": command,
            "exit_code": exit_code,
            "stderr": stderr,
            "stdout": stdout,
            "stderr_excerpt": self._truncate_diag_text(stderr, limit=1200),
            "stdout_excerpt": self._truncate_diag_text(stdout, limit=1200),
            "error_class": error_class,
            "error_message": error_message,
            "error_location": error_location,
            "failed_js_full": self._truncate_diag_text(candidate_js, limit=50000),
            "failed_js_with_line_no": numbered,
            "focus_windows": focus,
            "detected_api_violations": collect_detected_api_violations(candidate_js),
            "gate_summary": gate_summary,
        }
        if "preview_mode" in diag:
            context["preview_mode"] = diag.get("preview_mode")
        if "attempt" in diag:
            context["attempt"] = diag.get("attempt")
        return context

    async def _publish_retry_context_event(
        self,
        *,
        run_id: str,
        slide_no: int,
        repair_round: int,
        candidate_no: int,
        phase: str,
        issues: list[str],
        context: dict[str, Any],
    ) -> None:
        error_location = context.get("error_location", {}) if isinstance(context.get("error_location", {}), dict) else {}
        gate_summary = context.get("gate_summary", {}) if isinstance(context.get("gate_summary", {}), dict) else {}
        await self._publish(
            run_id,
            EventType.SLIDE_RETRY_CONTEXT_BUILT,
            {
                "slide_no": slide_no,
                "round": repair_round,
                "candidate": candidate_no,
                "phase": phase,
                "issue_count": len(issues or []),
                "failing_js_path": context.get("slide_js_path", ""),
                "stderr_excerpt": context.get("stderr_excerpt", ""),
                "error_location": error_location,
                "gate_summary": gate_summary,
                "attempt": context.get("attempt"),
            },
        )

    def _validate_slide_js_contract(
        self,
        js_code: str,
        *,
        slide_no: int,
        page_type: str,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
    ) -> list[str]:
        issues: list[str] = []
        export_ok = False
        export_match = re.search(r"module\.exports\s*=\s*\{([\s\S]{0,1400}?)\}\s*;", js_code)
        if export_match:
            export_body = export_match.group(1)
            export_ok = ("createSlide" in export_body) and ("slideConfig" in export_body)
        if not export_ok:
            issues.append("missing export contract")
        if not re.search(r"\bfunction\s+createSlide\s*\(\s*pres\s*,\s*theme\s*\)", js_code):
            issues.append("createSlide signature invalid")
        if "async function createSlide" in js_code:
            issues.append("createSlide must be synchronous")
        if "addGroup(" in js_code:
            issues.append("forbidden api detected: addGroup()")
        if "slide.addPageBadge(" in js_code:
            issues.append("forbidden api detected: slide.addPageBadge()")
        if "createCanvas(" in js_code:
            issues.append("forbidden runtime dependency: createCanvas()")
        if re.search(r"addShape\(\s*['\"][a-zA-Z0-9_-]+['\"]", js_code):
            issues.append("addShape must use pres.shapes enum, not string literal")
        issues.extend(
            collect_addshape_signature_issues(
                js_code,
                extract_method_call_args=lambda payload, method_expr: self._extract_method_call_args(payload, method_expr=method_expr),
                dedupe=self._dedupe_preserve_order,
            )
        )
        issues.extend(
            collect_addtext_signature_issues(
                js_code,
                extract_method_call_args=lambda payload, method_expr: self._extract_method_call_args(payload, method_expr=method_expr),
                dedupe=self._dedupe_preserve_order,
            )
        )
        if re.search(r"addShape\(\s*pres\.shapes\.LINE[\s\S]*?\{[\s\S]*?\b(?:w|h)\s*:\s*0(?:\.0+)?\b", js_code):
            issues.append("line shape geometry invalid: w/h must be > 0")
        if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", js_code):
            issues.append("hex color with # is forbidden")
        if re.search(r"['\"][0-9a-fA-F]{8}['\"]", js_code):
            issues.append("8-char hex color is forbidden")
        issues.extend(
            collect_addimage_signature_issues(
                js_code,
                extract_method_call_args=lambda payload, method_expr: self._extract_method_call_args(payload, method_expr=method_expr),
                dedupe=self._dedupe_preserve_order,
            )
        )
        if slide_no > 1 and "x: 9.3, y: 5.1" not in js_code:
            issues.append("missing required page badge position")
        if any(char in js_code for char in ("•", "✓", "▪", "◦")):
            issues.append("unicode bullet symbol detected")
        planned_assets = extract_planned_asset_paths(js_code=js_code, slide_plan=slide_plan, dedupe=self._dedupe_preserve_order)
        main_asset = extract_main_asset_path(js_code=js_code, slide_plan=slide_plan, dedupe=self._dedupe_preserve_order)
        if page_type == "content" and all(token not in js_code for token in ("addShape(", "addImage(", "addChart(")):
            issues.append("content slide missing non-text visual element")
        if page_type == "content" and planned_assets:
            if "addImage(" not in js_code:
                issues.append("visual assets planned but addImage() missing")
            if main_asset and main_asset not in js_code:
                issues.append("visual assets planned but main image path not used")
            if has_image_placeholder_text(js_code):
                issues.append("image placeholder text remains while visual assets are planned")
        if page_type == "content":
            if visual_policy == VisualPolicy.MEDIA_REQUIRED:
                if "addImage(" not in js_code:
                    issues.append("visual_policy violation: media_required needs addImage()")
                if all(token not in js_code for token in ("addShape(", "addChart(")):
                    issues.append("visual_policy violation: media_required needs addShape()/addChart() complement")
            elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
                if "addImage(" in js_code:
                    issues.append("visual_policy violation: basic_graphics_only forbids addImage()")
        issues.extend(self._collect_js_style_issues(js_code=js_code, page_type=page_type))
        return self._dedupe_preserve_order(issues)

    def _extract_method_call_args(self, js_code: str, *, method_expr: str) -> list[list[str]]:
        payload = str(js_code or "")
        pattern = re.compile(method_expr)
        calls: list[list[str]] = []
        idx = 0
        n = len(payload)
        while idx < n:
            match = pattern.search(payload, idx)
            if not match:
                break
            open_idx = payload.find("(", match.start())
            if open_idx < 0:
                idx = match.end()
                continue

            depth = 0
            in_single = False
            in_double = False
            in_backtick = False
            escaped = False
            close_idx = -1
            pos = open_idx
            while pos < n:
                ch = payload[pos]
                if escaped:
                    escaped = False
                    pos += 1
                    continue
                if ch == "\\":
                    escaped = True
                    pos += 1
                    continue
                if in_single:
                    if ch == "'":
                        in_single = False
                    pos += 1
                    continue
                if in_double:
                    if ch == '"':
                        in_double = False
                    pos += 1
                    continue
                if in_backtick:
                    if ch == "`":
                        in_backtick = False
                    pos += 1
                    continue
                if ch == "'":
                    in_single = True
                    pos += 1
                    continue
                if ch == '"':
                    in_double = True
                    pos += 1
                    continue
                if ch == "`":
                    in_backtick = True
                    pos += 1
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        close_idx = pos
                        break
                pos += 1

            if close_idx <= open_idx:
                idx = match.end()
                continue

            raw_args = payload[open_idx + 1 : close_idx]
            calls.append(self._split_top_level_args(raw_args))
            idx = close_idx + 1

        return calls

    def _apply_local_js_guardrails(
        self,
        *,
        js_code: str,
        slide_no: int,
        page_type: SlidePageType,
    ) -> str:
        guarded = str(js_code or "")
        guarded = self._ensure_create_slide_returns_slide(guarded)
        guarded = self._ensure_slide_config_index(guarded, slide_no=slide_no)
        guarded = self._ensure_title_text_guardrails(guarded)
        guarded = self._ensure_rows_text_guardrails(guarded)
        guarded = self._ensure_line_positive_geometry(guarded)
        if page_type != SlidePageType.COVER and slide_no > 1:
            guarded = self._ensure_page_badge_position(guarded, slide_no=slide_no)
        return guarded

    def _has_valid_page_badge(self, *, js_code: str, slide_no: int) -> bool:
        if slide_no <= 1:
            return True
        payload = str(js_code or "")
        has_xy = "x: 9.3, y: 5.1" in payload
        has_helper_call = bool(re.search(r"\baddPageBadge\s*\(\s*pres\s*,\s*slide\s*,\s*theme", payload))
        has_inline = (
            bool(re.search(r"slide\.addShape\(\s*pres\.shapes\.(?:OVAL|ROUNDED_RECTANGLE)\s*,\s*\{[^{}]*x\s*:\s*9\.3[^{}]*y\s*:\s*5\.1", payload, flags=re.S))
            and bool(re.search(r"slide\.addText\([^)]*x\s*:\s*9\.3[^)]*y\s*:\s*5\.1", payload, flags=re.S))
        )
        return bool(has_xy and (has_helper_call or has_inline))

    def _ensure_create_slide_returns_slide(self, js_code: str) -> str:
        fixed = str(js_code or "")
        fixed, count = re.subn(
            r"(?m)^\s*return\s*\{\s*createSlide\s*,\s*slideConfig\s*\}\s*;\s*$",
            "  return slide;",
            fixed,
        )
        if count > 0:
            return fixed
        if not re.search(r"\bfunction\s+createSlide\s*\(", fixed):
            return fixed
        if re.search(r"(?m)^\s*return\s+slide\s*;\s*$", fixed):
            return fixed
        marker = "module.exports = { createSlide, slideConfig };"
        if marker in fixed:
            idx = fixed.find(marker)
            prefix = fixed[:idx]
            suffix = fixed[idx:]
            if "}" in prefix:
                last_brace = prefix.rfind("}")
                if last_brace >= 0:
                    prefix = prefix[:last_brace] + "  return slide;\n" + prefix[last_brace:]
                    return prefix + suffix
        return fixed

    def _ensure_slide_config_index(self, js_code: str, *, slide_no: int) -> str:
        fixed = str(js_code or "")
        fixed, count = re.subn(
            r"(\b(?:const|let|var)\s+slideConfig\s*=\s*\{[\s\S]*?\bindex\s*:\s*)\d+",
            rf"\g<1>{slide_no}",
            fixed,
            count=1,
        )
        if count > 0:
            return fixed
        if re.search(r"\b(?:const|let|var)\s+slideConfig\s*=\s*\{", fixed):
            fixed = re.sub(
                r"(\b(?:const|let|var)\s+slideConfig\s*=\s*\{)",
                rf"\1\n  index: {slide_no},",
                fixed,
                count=1,
            )
        return fixed

    def _ensure_title_text_guardrails(self, js_code: str) -> str:
        def repl(match: re.Match[str]) -> str:
            options = match.group(1)
            updated = options
            font_match = re.search(r"\bfontSize\s*:\s*([0-9]+(?:\.[0-9]+)?)", updated)
            if font_match:
                try:
                    if float(font_match.group(1)) < 36.0:
                        updated = re.sub(r"\bfontSize\s*:\s*[0-9]+(?:\.[0-9]+)?", "fontSize: 38", updated, count=1)
                except ValueError:
                    updated = re.sub(r"\bfontSize\s*:\s*[0-9]+(?:\.[0-9]+)?", "fontSize: 38", updated, count=1)
            else:
                updated = f"fontSize: 38, {updated}"
            if not re.search(r"\balign\s*:", updated):
                updated = updated.rstrip() + ", align: 'left'"
            if not re.search(r"\bfit\s*:", updated):
                updated = updated.rstrip() + ", fit: 'shrink'"
            return f"slide.addText(slideConfig.title, {{{updated}}});"

        return re.sub(
            r"slide\.addText\(\s*slideConfig\.title\s*,\s*\{([^{}]*)\}\s*\);",
            repl,
            js_code,
        )

    def _ensure_rows_text_guardrails(self, js_code: str) -> str:
        def repl(match: re.Match[str]) -> str:
            options = match.group(1)
            updated = options
            if not re.search(r"\balign\s*:", updated):
                updated = updated.rstrip() + ", align: 'left'"
            if not re.search(r"\bbold\s*:", updated):
                updated = updated.rstrip() + ", bold: false"
            if not re.search(r"\bfit\s*:", updated):
                updated = updated.rstrip() + ", fit: 'shrink'"
            return f"slide.addText(rows, {{{updated}}});"

        return re.sub(
            r"slide\.addText\(\s*rows\s*,\s*\{([^{}]*)\}\s*\);",
            repl,
            js_code,
        )

    def _ensure_line_positive_geometry(self, js_code: str) -> str:
        fixed = re.sub(
            r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bw\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))",
            r"\g<1>0.01",
            js_code,
            flags=re.S,
        )
        fixed = re.sub(
            r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bh\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))",
            r"\g<1>0.01",
            fixed,
            flags=re.S,
        )
        return fixed

    def _ensure_page_badge_position(self, js_code: str, *, slide_no: int) -> str:
        if self._has_valid_page_badge(js_code=js_code, slide_no=slide_no):
            return js_code
        if "function createSlide(" not in js_code:
            return js_code
        updated = js_code
        if "function addPageBadge(" not in updated:
            badge_helper = "\n".join(
                [
                    "function addPageBadge(pres, slide, theme, n) {",
                    "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "}",
                    "",
                ]
            )
            updated = updated.replace("function createSlide(", badge_helper + "function createSlide(", 1)
        if re.search(r"\baddPageBadge\s*\(\s*pres\s*,\s*slide\s*,\s*theme", updated):
            return updated
        badge_snippet = "\n".join(
            [
                "  addPageBadge(pres, slide, theme, slideConfig.index || 1);",
            ]
        )
        if "return slide;" in updated:
            return updated.replace("return slide;", badge_snippet + "\n  return slide;", 1)
        return updated

    def _classify_slide_issues(self, issues: list[str]) -> dict[str, list[str]]:
        blocking_markers = (
            "candidate build failed",
            "missing export contract",
            "createSlide signature invalid",
            "createSlide must be synchronous",
            "preview compile failed",
            "preview pptx missing",
            "out of slide bounds",
            "overlaps box",
            "visual_policy violation",
            "forbidden api detected",
            "forbidden runtime dependency",
            "addShape must use pres.shapes enum",
            "addText call signature invalid",
            "addShape call signature invalid",
            "addImage call signature invalid",
            "line shape geometry invalid",
            "hex color with # is forbidden",
            "8-char hex color is forbidden",
            "visual assets planned but addImage() missing",
            "visual assets planned but main image path not used",
            "image placeholder text remains while visual assets are planned",
            "llm_output_not_executable",
        )
        high_risk_markers = (
            "body text must be left-aligned",
            "body text should not use bold",
            "body text missing fit:'shrink'",
            "title missing fit:'shrink'",
            "title font too small",
            "title/body size contrast too weak",
            "missing required page badge position",
            "margin too tight",
            "gap too tight",
            "content slide missing non-text visual element",
            "theme key usage incomplete",
        )

        blocking: list[str] = []
        high_risk: list[str] = []
        warnings: list[str] = []
        for issue in issues:
            text = str(issue).strip()
            if not text:
                continue
            lowered = text.lower()
            if any(marker.lower() in lowered for marker in blocking_markers):
                blocking.append(text)
            elif any(marker.lower() in lowered for marker in high_risk_markers):
                high_risk.append(text)
            else:
                warnings.append(text)

        return {
            "blocking": self._dedupe_preserve_order(blocking),
            "high_risk": self._dedupe_preserve_order(high_risk),
            "warnings": self._dedupe_preserve_order(warnings),
        }

    def _local_quality_score(self, *, classified: dict[str, list[str]]) -> int:
        blocking = len(classified.get("blocking", []))
        high_risk = len(classified.get("high_risk", []))
        warnings = len(classified.get("warnings", []))
        score = 100 - blocking * 24 - high_risk * 12 - warnings * 3
        return max(0, min(100, score))

    def _build_local_repair_directives(self, *, classified: dict[str, list[str]]) -> list[str]:
        blocking = classified.get("blocking", [])
        high_risk = classified.get("high_risk", [])
        directives: list[str] = []

        if any("export" in item.lower() or "signature" in item.lower() for item in blocking):
            directives.append("Enforce contract exactly: function createSlide(pres, theme) + module.exports = { createSlide, slideConfig }.")
        if any("preview compile failed" in item.lower() or "forbidden api" in item.lower() for item in blocking):
            directives.append("Use pptxgenjs legal API only: slide.background = { color: theme.bg }; addShape with pres.shapes.*; never ShapeType/slide.shapes/addGroup.")
        if any("line shape geometry invalid" in item.lower() for item in blocking):
            directives.append("For pres.shapes.LINE always keep both w and h > 0 (e.g., h: 0.01), never zero-length geometry.")
        if any("addtext call signature invalid" in item.lower() or "addshape call signature invalid" in item.lower() for item in blocking):
            directives.append("Call signatures must be strict: addText(textOrRuns, { ...opts }) and addShape(pres.shapes.X, { ...opts }); never pass style as 3rd arg or positional x,y,w,h.")
        if any("addimage call signature invalid" in item.lower() for item in blocking):
            directives.append("Use strict image API signature only: slide.addImage({ path|data, x, y, w, h, ...opts }); never addImage(path, opts).")
        if any("visual assets planned but addimage() missing" in item.lower() or "main image path not used" in item.lower() for item in blocking):
            directives.append("When visual assets are planned, consume slot='main' via explicit addImage({ path: <main-path>, ... }).")
        if any("image placeholder text remains while visual assets are planned" in item.lower() for item in blocking + high_risk):
            directives.append("Remove image placeholder labels and render real images from visual_plan.assets instead.")
        if any("out of slide bounds" in item.lower() or "overlaps" in item.lower() for item in blocking + high_risk):
            directives.append("Reflow layout with safe margins and non-overlap: content margins >=0.5in, preserve 0.22in+ block gap.")
        if any("page badge" in item.lower() for item in blocking):
            directives.append("Add page badge on non-cover slides via addPageBadge() at x:9.3, y:5.1.")
        if any("left-aligned" in item.lower() for item in high_risk):
            directives.append("Left-align body paragraphs/lists; center only title or badge text.")
        if any("fit:'shrink'" in item.lower() for item in high_risk):
            directives.append("Apply fit:'shrink' to title and long body text blocks to prevent overflow.")
        if any("title font too small" in item.lower() or "size contrast" in item.lower() for item in high_risk):
            directives.append("Strengthen hierarchy: title >=36pt and at least 18pt larger than body text.")
        if any("content slide missing non-text visual element" in item.lower() for item in high_risk):
            directives.append("Ensure content slide contains at least one non-text element: addShape/addImage/addChart.")

        if not directives and (blocking or high_risk):
            directives.append("Fix all blocking/high-risk issues without changing the slide topic, page type, or narrative intent.")

        return self._dedupe_preserve_order(directives)

    def _issues_have_fatal_markers(self, issues: list[str]) -> bool:
        markers = (
            "missing export contract",
            "createSlide signature invalid",
            "createSlide must be synchronous",
            "preview compile failed",
            "preview pptx missing",
            "jsondecodeerror",
            "llm_output_not_executable",
        )
        for issue in issues:
            text = str(issue)
            if any(marker in text for marker in markers):
                return True
        return False

    def _persist_failed_candidate_js(
        self,
        *,
        slides_dir: Path,
        slide_no: int,
        js_code: str,
        round_no: int,
        issues: list[str],
    ) -> None:
        failed_dir = slides_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        failed_js = failed_dir / f"slide-{slide_no:02d}-last.js"
        failed_meta = failed_dir / f"slide-{slide_no:02d}-last.meta.json"
        failed_js.write_text(js_code, encoding="utf-8")
        failed_meta.write_text(
            json.dumps(
                {
                    "slide_no": slide_no,
                    "round": round_no,
                    "issues": issues[:20],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _split_qa_issues_by_slide(self, issues: list[str]) -> tuple[dict[int, list[str]], list[str]]:
        per_slide: dict[int, list[str]] = {}
        global_issues: list[str] = []
        for item in issues:
            text = str(item or "").strip()
            if not text:
                continue
            match = re.match(r"slide-(\d{2})(?:-[^:]+)?\.js:\s*(.+)", text, flags=re.IGNORECASE)
            if not match:
                global_issues.append(text)
                continue
            slide_no = int(match.group(1))
            reason = (match.group(2) or "").strip() or text
            bucket = per_slide.setdefault(slide_no, [])
            bucket.append(reason)
        return {k: self._dedupe_preserve_order(v) for k, v in per_slide.items()}, self._dedupe_preserve_order(global_issues)

    async def _persist_qa_failure_artifacts(self, *, run_id: str, mode: GenerationMode) -> dict[str, Any]:
        run = await self.store.get_run(run_id)
        if run is None:
            return {}
        qa_report = run.qa_report if isinstance(run.qa_report, dict) else {}
        issues = [str(item) for item in qa_report.get("issues", []) if str(item).strip()] if isinstance(qa_report.get("issues", []), list) else []
        issues_by_slide, global_issues = self._split_qa_issues_by_slide(issues)

        artifact_dir = Path(run.artifact_dir)
        report_path = artifact_dir / "qa_failed_issues.json"
        payload = {
            "run_id": run_id,
            "mode": mode.value,
            "issue_count": len(issues),
            "issues": issues[:200],
            "issues_by_slide": {str(k): v for k, v in sorted(issues_by_slide.items(), key=lambda x: x[0])},
            "global_issues": global_issues[:80],
            "qa_blocking_rules": [
                {
                    "slide_no": slide_no,
                    "rule_name": reasons[0] if reasons else "",
                    "source_stage": "final_qa",
                }
                for slide_no, reasons in sorted(issues_by_slide.items(), key=lambda x: x[0])
                if reasons
            ][:80],
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        copied: list[str] = []
        if mode == GenerationMode.SCRATCH:
            slides_dir = artifact_dir / "slides"
            failed_dir = slides_dir / "failed"
            failed_dir.mkdir(parents=True, exist_ok=True)
            for slide_no, reasons in sorted(issues_by_slide.items(), key=lambda x: x[0]):
                src = slides_dir / f"slide-{slide_no:02d}.js"
                if not src.exists():
                    continue
                dst = failed_dir / f"slide-{slide_no:02d}-last.js"
                meta = failed_dir / f"slide-{slide_no:02d}-last.meta.json"
                shutil.copy2(src, dst)
                meta.write_text(
                    json.dumps(
                        {
                            "slide_no": slide_no,
                            "round": None,
                            "issues": reasons[:40],
                            "source": "final_qa",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                copied.append(str(dst))

        return {
            "qa_failed_report": str(report_path),
            "qa_issue_count": len(issues),
            "qa_blocking_rule_count": len(payload["qa_blocking_rules"]),
            "qa_blocking_rules": payload["qa_blocking_rules"],
            "failed_slide_js": copied,
        }

    def _collect_js_style_issues(self, *, js_code: str, page_type: str) -> list[str]:
        issues: list[str] = []
        boxes = self._collect_js_layout_boxes(js_code)
        if not boxes:
            return issues

        major_boxes = [
            box
            for box in boxes
            if not self._is_js_page_badge_box(box)
            and (box.element_type in {"text", "image", "chart"} or box.area >= 0.45)
        ]
        margin_floor = 0.5 if page_type == "content" else 0.35

        for idx, box in enumerate(major_boxes, start=1):
            if box.x < -0.01 or box.y < -0.01 or box.x + box.w > SLIDE_WIDTH_IN + 0.01 or box.y + box.h > SLIDE_HEIGHT_IN + 0.01:
                issues.append(f"box-{idx} out of slide bounds")
                continue
            if page_type == "content":
                left = box.x
                top = box.y
                right = SLIDE_WIDTH_IN - (box.x + box.w)
                bottom = SLIDE_HEIGHT_IN - (box.y + box.h)
                lowered_expr = box.text_expr.lower()
                is_title_box = box.element_type == "text" and "slideconfig.title" in lowered_expr
                if is_title_box:
                    if min(left, right) < margin_floor - 0.03:
                        issues.append(f"box-{idx} horizontal margin too tight (<{margin_floor:.1f}in)")
                elif min(left, right, top, bottom) < margin_floor - 0.03:
                    issues.append(f"box-{idx} margin too tight (<{margin_floor:.1f}in)")

        for i in range(len(major_boxes)):
            for j in range(i + 1, len(major_boxes)):
                if major_boxes[i].element_type == "shape" and major_boxes[j].element_type == "shape":
                    continue
                if self._is_js_intentional_container_overlap(major_boxes[i], major_boxes[j]):
                    continue
                overlap_ratio = self._js_box_overlap_ratio(major_boxes[i], major_boxes[j])
                if overlap_ratio >= 0.12:
                    issues.append(f"box-{i + 1} overlaps box-{j + 1} (ratio={overlap_ratio:.2f})")
                if page_type == "content":
                    gap = self._js_major_block_gap(major_boxes[i], major_boxes[j])
                    if gap is not None and 0 < gap < 0.22:
                        issues.append(f"box-{i + 1} and box-{j + 1} gap too tight ({gap:.2f}\" < 0.22\")")

        text_boxes = [box for box in boxes if box.element_type == "text" and not self._is_js_page_badge_box(box)]
        title_box = next((box for box in text_boxes if "slideconfig.title" in box.text_expr.lower()), None)
        body_font_sizes: list[float] = []
        for box in text_boxes:
            looks_like_body = self._is_js_body_text_candidate(box)
            if looks_like_body and box.font_size is not None:
                body_font_sizes.append(box.font_size)
            if page_type == "content" and looks_like_body:
                if (box.align or "").lower() == "center" and box.h >= 0.32:
                    issues.append("body text must be left-aligned (center detected)")
                if box.bold is True and (box.font_size is None or box.font_size <= 18):
                    issues.append("body text should not use bold")
                if box.w >= 1.2 and box.h >= 0.45 and (box.fit or "").lower() != "shrink":
                    issues.append("body text missing fit:'shrink'")

        if title_box is not None:
            if (title_box.fit or "").lower() != "shrink":
                issues.append("title missing fit:'shrink'")
            if title_box.font_size is not None:
                if title_box.font_size < 36:
                    issues.append(f"title font too small ({title_box.font_size:.0f} < 36)")
                if body_font_sizes and title_box.font_size < max(body_font_sizes) + 18:
                    issues.append("title/body size contrast too weak")

        return self._dedupe_preserve_order(issues)

    def _is_js_body_text_candidate(self, box: JsLayoutBox) -> bool:
        if box.element_type != "text":
            return False
        lowered_expr = box.text_expr.lower()
        if "slideconfig.title" in lowered_expr:
            return False

        literal_match = re.fullmatch(r"['\"]([^'\"]*)['\"]", box.text_expr.strip(), flags=re.DOTALL)
        if literal_match:
            literal_text = re.sub(r"\s+", " ", literal_match.group(1)).strip()
            if literal_text and len(literal_text) <= 24 and len(literal_text.split()) <= 4:
                # Treat short static labels (for example "Visual", "Track A") as decorative heading/caption text.
                return False

        signal_tokens = ("bullets", "rows", "item", "note", "takeaway", "payload", "prepared", "join(")
        if any(token in lowered_expr for token in signal_tokens):
            return True

        if box.y < 1.0 or box.w < 1.4 or box.h < 0.34:
            return False
        if box.font_size is not None and box.font_size >= 20:
            return False
        return True

    def _collect_js_layout_boxes(self, js_code: str) -> list[JsLayoutBox]:
        boxes: list[JsLayoutBox] = []
        for method in ("addText", "addShape", "addImage", "addChart"):
            for first_arg, options_raw in self._extract_slide_method_calls(js_code, method):
                x = self._parse_js_float_option(options_raw, "x")
                y = self._parse_js_float_option(options_raw, "y")
                w = self._parse_js_float_option(options_raw, "w")
                h = self._parse_js_float_option(options_raw, "h")
                if x is None or y is None or w is None or h is None or w <= 0 or h <= 0:
                    continue
                element_type = "text" if method == "addText" else ("shape" if method == "addShape" else ("image" if method == "addImage" else "chart"))
                boxes.append(
                    JsLayoutBox(
                        element_type=element_type,
                        x=x,
                        y=y,
                        w=w,
                        h=h,
                        text_expr=first_arg,
                        options_raw=options_raw,
                        font_size=self._parse_js_float_option(options_raw, "fontSize") if method == "addText" else None,
                        align=self._parse_js_string_option(options_raw, "align") if method == "addText" else None,
                        bold=self._parse_js_bool_option(options_raw, "bold") if method == "addText" else None,
                        fit=self._parse_js_string_option(options_raw, "fit") if method == "addText" else None,
                    )
                )
        return boxes

    def _extract_slide_method_calls(self, js_code: str, method: str) -> list[tuple[str, str]]:
        token = f"slide.{method}("
        calls: list[tuple[str, str]] = []
        cursor = 0
        while True:
            start = js_code.find(token, cursor)
            if start < 0:
                break
            open_idx = start + len(token) - 1
            close_idx = self._find_matching_delimiter(js_code, start_idx=open_idx, open_char="(", close_char=")")
            if close_idx < 0:
                cursor = start + len(token)
                continue
            args_raw = js_code[open_idx + 1 : close_idx]
            parts = self._split_top_level_args(args_raw)
            if len(parts) >= 2:
                calls.append((parts[0].strip(), parts[1].strip()))
            cursor = close_idx + 1
        return calls

    def _find_matching_delimiter(self, text: str, *, start_idx: int, open_char: str, close_char: str) -> int:
        depth = 0
        quote: str | None = None
        escape = False
        for idx in range(start_idx, len(text)):
            ch = text[idx]
            if quote is not None:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in {"'", '"', "`"}:
                quote = ch
                continue
            if ch == open_char:
                depth += 1
                continue
            if ch == close_char:
                depth -= 1
                if depth == 0:
                    return idx
        return -1

    def _split_top_level_args(self, raw_args: str) -> list[str]:
        parts: list[str] = []
        buf: list[str] = []
        depth_round = 0
        depth_curly = 0
        depth_square = 0
        quote: str | None = None
        escape = False

        for ch in raw_args:
            if quote is not None:
                buf.append(ch)
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in {"'", '"', "`"}:
                quote = ch
                buf.append(ch)
                continue
            if ch == "(":
                depth_round += 1
            elif ch == ")":
                depth_round = max(0, depth_round - 1)
            elif ch == "{":
                depth_curly += 1
            elif ch == "}":
                depth_curly = max(0, depth_curly - 1)
            elif ch == "[":
                depth_square += 1
            elif ch == "]":
                depth_square = max(0, depth_square - 1)
            elif ch == "," and depth_round == 0 and depth_curly == 0 and depth_square == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
            buf.append(ch)

        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
        return parts

    def _parse_js_float_option(self, options_raw: str, key: str) -> float | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(-?\d+(?:\.\d+)?)\b", options_raw)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _parse_js_string_option(self, options_raw: str, key: str) -> str | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(['\"])(.*?)\1", options_raw, flags=re.S)
        if not match:
            return None
        return match.group(2).strip()

    def _parse_js_bool_option(self, options_raw: str, key: str) -> bool | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(true|false)\b", options_raw)
        if not match:
            return None
        return match.group(1) == "true"

    def _is_js_page_badge_box(self, box: JsLayoutBox) -> bool:
        if box.x >= 9.1 and box.y >= 5.0 and box.w <= 0.7 and box.h <= 0.7:
            return True
        lowered = box.text_expr.lower()
        if "slideconfig.index" in lowered and box.w <= 0.8 and box.h <= 0.8:
            return True
        return False

    def _is_js_intentional_container_overlap(self, left: JsLayoutBox, right: JsLayoutBox) -> bool:
        if left.element_type == right.element_type:
            return False
        if "shape" not in {left.element_type, right.element_type}:
            return False
        container = left if left.element_type == "shape" else right
        inner = right if container is left else left
        tol = 0.08
        inside = (
            inner.x >= container.x - tol
            and inner.y >= container.y - tol
            and inner.x + inner.w <= container.x + container.w + tol
            and inner.y + inner.h <= container.y + container.h + tol
        )
        if not inside:
            return False
        if container.area <= 0:
            return False
        ratio = inner.area / container.area
        return 0.05 <= ratio <= 0.95

    def _js_box_overlap_ratio(self, left: JsLayoutBox, right: JsLayoutBox) -> float:
        x_overlap = max(0.0, min(left.x + left.w, right.x + right.w) - max(left.x, right.x))
        y_overlap = max(0.0, min(left.y + left.h, right.y + right.h) - max(left.y, right.y))
        if x_overlap <= 0 or y_overlap <= 0:
            return 0.0
        overlap_area = x_overlap * y_overlap
        min_area = min(left.area, right.area)
        if min_area <= 0:
            return 0.0
        return overlap_area / min_area

    def _js_major_block_gap(self, left: JsLayoutBox, right: JsLayoutBox) -> float | None:
        x_overlap = min(left.x + left.w, right.x + right.w) - max(left.x, right.x)
        y_overlap = min(left.y + left.h, right.y + right.h) - max(left.y, right.y)
        if x_overlap > 0:
            if left.y <= right.y:
                return max(0.0, right.y - (left.y + left.h))
            return max(0.0, left.y - (right.y + right.h))
        if y_overlap > 0:
            if left.x <= right.x:
                return max(0.0, right.x - (left.x + left.w))
            return max(0.0, left.x - (right.x + right.w))
        return None

    def _dedupe_preserve_order(self, issues: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in issues:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _fallback_quality_gate(self, *, hard_issues: list[str], preview_text: str, candidate_js: str) -> dict[str, Any]:
        score = 92 - len(hard_issues) * 15
        text = (preview_text or "").strip()
        lowered = candidate_js.lower()
        issues: list[str] = []
        directives: list[str] = []
        if len(text) < 20:
            score -= 18
            issues.append("preview text too short")
            directives.append("expand concrete natural-language copy")
        if re.search(r"(placeholder|lorem|ipsum|todo|xxxx|\[[^\]]*(主视觉|辅助图|流程图|示意图|image)\])", lowered):
            score -= 25
            issues.append("placeholder-like code/text remains")
            directives.append("replace placeholders with natural language")
        score = max(0, min(100, int(score)))
        return {"score": score, "issues": issues, "repair_directives": directives}

