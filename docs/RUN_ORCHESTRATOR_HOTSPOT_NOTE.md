# Run Orchestrator Hotspot Note

## Current Status

`service/run/orchestrator.py` is still a transitional hotspot.

That status is intentional and honest:

- Diego already moved major stage behavior into `run/flows`
- compile, quality/repair, and reporting behavior already have explicit service-owned modules
- `orchestrator.py` still carries a large compatibility and lifecycle surface while migration continues

It should therefore be treated as a transition facade, not as the desired final
home for more business logic.

## What The Orchestrator Should Own

The orchestrator remains the place for:

- lifecycle orchestration
- explicit run-state transition control
- flow delegation
- failure convergence
- high-level runtime wiring that is still migration-bound
- compatibility aliases that still need to exist during migration

`build_orchestrator`-style dependency construction is healthier in a separate
factory boundary than at the bottom of the hotspot file.

## What Should Keep Moving Out

The orchestrator should keep shrinking by pushing detailed behavior into owned
modules such as:

- `run/flows/*` for stage execution
- `run/services/*` for compile, quality/repair, and reporting logic
- `run/engines/*` for explicit engine-facing composition seams
- `run/factory.py` for public construction and dependency wiring
- `run/slide_preview.py` for pure preview payload, fallback, and preview-runner helpers
- `run/preview_qa.py` for preview compile diagnostics and markitdown-based preview QA checks
- `run/slide_scene.py` for scene parsing and scene-to-outline projection helpers
- `run/slide_plan_rules.py` and `run/slide_spec_repair.py` for pure slide planning and repair rules
- `run/slide_generation_briefs.py` for slide brief shaping and fallback brief helpers
- `run/outline_reporting.py` for requirements-analysis, outline-repair, research, and plan event payload shaping
- `run/slide_candidate_reporting.py` for candidate-level event/report payload shaping
- `run/slide_candidate_decisions.py` for candidate accept/degrade/exhaust decision rules
- `run/slide_candidate_state.py` for candidate-loop state and best-candidate tracking
- `run/slide_candidate_execution.py` for candidate build/review execution and auto-fix publishing
- `run/slide_candidate_review.py` for preview QA, contract gate, and candidate review result shaping
- `run/slide_candidate_finalize.py` for repair-cycle events, exhaustion details, and final artifact/report payload shaping
- `run/qa_reporting.py` for QA history, preview-cache, and final QA report shaping
- `run/qa_static_checks.py` for deterministic scratch-slide static QA evaluation
- `run/qa_preview_sampling.py` for preview-check decisions and unchanged-preview sampling rules
- `run/qa_mode_execution.py` for scratch/template QA execution paths and mode-local issue collection
- `run/services/slide_regeneration_service.py` for scene-save recompilation and single-slide regeneration execution
- `run/slide_regeneration_reporting.py` for regenerate preview payload and instruction-rule shaping
- `run/scene_recompile.py` for scene-save recompilation rules
- `run/template_slide_regeneration.py` for template-mode single-slide regeneration execution
- `run/template_apply_reporting.py` for template slot-mapping, layout, and chart-truth report payload shaping
- `run/repair_mode_execution.py` for one-round scratch/template repair execution and template failure mapping
- `run/repair_round_reporting.py` for repair-round history, event payloads, and verification-cycle updates
- `service/slides/skill_slide_renderer.py` and `service/slides/skill_slide_blocks.py` for JS rendering and block composition rules
- `service/templates/template_structure_rebuild.py` for PPT template package structure rebuilding and relationship/content-type normalization
- `service/templates/template_slot_mapping.py` for template placeholder graph extraction and slot-mapping planning
- `service/templates/template_layout_reflow.py` for deterministic template layout box extraction, overlap checks, and local reflow
- `service/design/design_resolution.py` for style selection, requirements shaping, and design-profile resolution
- `run/runtime_support.py` for legacy capability composition that has not yet been retired

## Forbidden Growth Pattern

Do not use `orchestrator.py` as the easiest place to put:

- slide-specific implementation details
- template-specific implementation details
- report formatting logic
- provider transport logic
- random shared helpers
- shell/workbench semantics

If new behavior cannot be named as lifecycle orchestration, flow delegation,
failure convergence, or explicit runtime wiring, it likely belongs somewhere
else.

## Near-Term Governance Direction

The next healthy direction is not a fake full rewrite.

The next healthy direction is:

- keep `orchestrator.py` readable as the lifecycle map
- continue extracting stage detail into explicit owned modules
- preserve truthful compatibility shims while they are still needed
- avoid adding vague dumping-ground modules under `service/run`

This keeps Diego honest about current reality while still moving toward a
clearer runtime kernel.
