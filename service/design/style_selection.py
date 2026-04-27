from __future__ import annotations

from ..models import GenerationMode, RunRecord, VisualPolicy
from .style_catalog import (
    STYLE_PRESET_AUTO,
    get_style_dna_by_id,
    resolve_style_choice,
    resolve_style_dna_choice,
)


def resolve_content_source_mode(run: RunRecord) -> str:
    return "rag_first" if run.input.rag_source_ids else "model_only"


def resolve_image_source_mode(*, run: RunRecord, asset_provider: str) -> str:
    if run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
        return "graphics_only"
    provider = str(asset_provider or "").lower().strip()
    if provider == "none":
        return "disabled"
    if provider == "mock":
        return "mock"
    return provider or "auto"


def selected_style_preset(run: RunRecord):
    if run.input.generation_mode != GenerationMode.SCRATCH:
        return None
    return resolve_style_choice(getattr(run.input, "style_preset", STYLE_PRESET_AUTO))


def selected_style_dna(run: RunRecord):
    if run.input.generation_mode != GenerationMode.SCRATCH:
        return None
    return resolve_style_dna_choice(
        getattr(run.input, "style_preset", STYLE_PRESET_AUTO),
        template_style=run.input.template_style,
        seed=f"{run.run_id}|{run.input.topic}",
    )


def resolved_style_dna_id(run: RunRecord) -> str | None:
    report = run.research_report if isinstance(run.research_report, dict) else {}
    design_intent = (
        report.get("design_intent", {})
        if isinstance(report.get("design_intent", {}), dict)
        else {}
    )
    style_dna_id = str(design_intent.get("style_dna_id", "")).strip()
    if style_dna_id:
        return style_dna_id
    selected = selected_style_dna(run)
    return selected.id if selected is not None else None


def resolved_style_dna(run: RunRecord):
    return get_style_dna_by_id(resolved_style_dna_id(run))


def requested_template_style(run: RunRecord) -> str:
    style_dna = selected_style_dna(run)
    if style_dna is not None:
        return style_dna.template_style_hint
    preset = selected_style_preset(run)
    if preset is not None:
        return preset.template_style_hint
    return run.input.template_style
