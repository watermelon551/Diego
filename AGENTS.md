# Diego Agent Guide

> Repository contract for AI coding agents and contributors working on Diego.
> Keep the service explicit, staged, observable, and focused on PPT generation.

## 1. Purpose

Diego is an independent PPT generation microservice.

It exists to turn a topic or prompt into a traceable, editable, and downloadable
presentation artifact through a controlled workflow:

`requirements analysis -> outline drafting -> outline confirmation -> slide generation or template editing -> compile -> QA / repair -> artifact return`

Diego owns:

- outline drafting and outline confirmation flow
- `scratch` slide generation
- `template`-based PPT editing
- compile orchestration and PPTX artifact production
- preview generation, QA, repair, and reporting
- run lifecycle state, SSE events, and failure semantics
- citation and report outputs needed to explain generation results

Diego does not own:

- identity, session, or permission truth
- formal project / artifact / reference truth
- generic retrieval engine semantics
- generic document render engine semantics
- Spectra UI flow or product-specific frontend behavior

If a change adds convenience but weakens state truthfulness, traceability, or
service boundary clarity, it is the wrong change.

## 2. Read First

Before meaningful changes, read:

1. [README.md](/Users/ln1/Projects/Spectra/diego/README.md)
2. [docs/PROJECT_GOALS.md](/Users/ln1/Projects/Spectra/diego/docs/PROJECT_GOALS.md)
3. [docs/ARCHITECTURE.md](/Users/ln1/Projects/Spectra/diego/docs/ARCHITECTURE.md)
4. [docs/SPECTRA_CHANGE_POINTS.md](/Users/ln1/Projects/Spectra/diego/docs/SPECTRA_CHANGE_POINTS.md)
5. [service/api/app.py](/Users/ln1/Projects/Spectra/diego/service/api/app.py)
6. [service/run/orchestrator.py](/Users/ln1/Projects/Spectra/diego/service/run/orchestrator.py)
7. relevant integration and service tests under [tests](/Users/ln1/Projects/Spectra/diego/tests)

Trust order:

1. tested behavior
2. service contracts and architecture docs
3. README and operational guidance
4. older notes and compatibility shims

If docs and code disagree, prefer tested behavior unless the docs clearly state
the intended target state.

## 3. Service Boundary

Treat Diego as a generation orchestrator, not as a generic app shell.

Preferred decomposition:

- `service/api`: HTTP transport, upload/download routes, SSE endpoint, error mapping
- `service/run`: run lifecycle, state transitions, flow orchestration, failure convergence
- `service/run/flows`: stage-specific execution for `outline`, `scratch`, and `template`
- `service/run/services`: compile, quality / repair, and reporting domain services
- `service/llm`: provider calls, protocol adaptation, parsing, and resilience helpers
- `service/slides`: scratch-side JS contract checks and quality gates
- `service/templates`: template mapping, layout operations, and asset application
- `service/design`: style selection, design profiles, layout and style policy
- `service/infra`: run storage, template storage, and event waiting primitives
- `service/models`: API DTOs, state contracts, and response models

Do not move Spectra-specific product semantics into Diego's core modules.

## 4. Core Invariants

These rules are non-optional:

1. Run state must remain explicit and truthful.
2. The outline confirmation gate must remain real.
3. Failure semantics are contract data, not debug leftovers.
4. `scratch` and `template` paths must stay explicit.
5. Reports, citations, and stage timings are first-class outputs.
6. Observability must describe the real path taken, including degraded paths.

Required run-state shape:

- `OUTLINE_DRAFTING`
- `AWAITING_OUTLINE_CONFIRM`
- `SLIDES_GENERATING`
- `COMPILING`
- `SUCCEEDED`
- `FAILED`

Rules:

- never skip `AWAITING_OUTLINE_CONFIRM` to start slide generation
- `FAILED` must carry `error_code` and `failed_stage`
- every meaningful run should preserve `run_id`, `trace_id`, `stage_timings`, and events
- `citation_map` should remain aligned with generated slide outputs when evidence exists
- per-slide retries must not corrupt global run state
- fallback or repair logic must not hide the original failure boundary

## 5. Architecture Rules

Prefer:

- thin FastAPI route handlers
- orchestration code that keeps stages explicit
- focused flow and service modules
- contract validation close to the boundary where it matters
- deterministic quality gates and repair decisions when possible
- compatibility shims only as migration edges, not as primary design surfaces

Avoid:

- putting template logic into scratch-only modules
- burying generation policy in random constants across unrelated files
- pushing provider-specific LLM behavior into API models
- shaping core contracts around one UI or one temporary integration
- silently downgrading failures into ambiguous success states
- adding broad `helpers` or `utils` dumping grounds for core behavior

### 5.1 Package By Feature

Default structural direction in Diego is `package by feature`, not endless flat
splitting inside one shared layer directory.

Rules:

- prefer feature-owned areas such as PPT run orchestration, slide scene editing,
  template editing, content generation, and compile runtime
- within a feature area, split oversized files by responsibility as needed
- do not stop at size-only splitting if the result is many tiny flat files in one directory
- when a facade remains, it should front a clearly owned feature package or compatibility seam
- shared code should stay small and exist only when reuse and ownership are both obvious

Refactoring heuristic:

- first place code by feature ownership
- then split large files inside that feature package
- avoid moving feature logic back into a generic layer-wide overflow folder

## 6. Hot Spots And File Ownership

### `service/run/orchestrator.py`

This is the current hot spot.

Allowed:

- lifecycle orchestration
- state transition control
- flow delegation
- failure convergence

Avoid adding more:

- large stage-specific business logic
- slide or template implementation details
- report formatting details
- provider-specific heuristics

Preferred direction:

- push stage behavior into `service/run/flows/*`
- push compile / QA / reporting logic into `service/run/services/*`
- keep the orchestrator readable as the run lifecycle map

### `service/api/app.py`

Keep this file transport-focused.

Allowed:

- route registration
- request validation handoff
- HTTP status mapping
- streaming response wiring

Avoid:

- business decisions
- direct file-format logic
- run-state mutation rules beyond transport validation

### `service/slides/*` and `service/templates/*`

These are separate capability areas.

Rules:

- scratch slide JS quality rules belong under `service/slides`
- template structure and layout behavior belong under `service/templates`
- shared concerns should be extracted only when the ownership remains obvious
- do not mix both paths back into one catch-all module without a strong reason

## 7. Coding Discipline

### 7.1 Keep stages explicit

Do not collapse requirements analysis, outline drafting, slide generation,
compile, QA, repair, and reporting into one giant function.

### 7.2 Keep contracts formal

If the system reasons about something repeatedly, give it an explicit contract
in `service/models` or a clearly owned module.

Prefer stable terms like:

- `run`
- `status`
- `stage`
- `outline`
- `slide`
- `artifact`
- `report`
- `citation`
- `retryable`
- `error_code`

Avoid vague names like `data`, `payload`, `manager`, `processor`, or `handler`
when they hide multiple responsibilities.

### 7.3 No vague dumping grounds

Do not create `utils`, `helpers`, `misc`, or `common` packages for core service
semantics.

Only extract shared code when:

- the reuse is real
- the ownership is clear
- the extracted name communicates responsibility

### 7.4 Comments should explain contracts

Comments should explain:

- why a state transition exists
- what a quality gate protects
- why a fallback or repair path is safe
- what a report field or trace field means

Do not add comments that only narrate obvious syntax.

### 7.5 Default repository language is English

Unless the user explicitly requests another language, use English for:

- code comments
- repository-facing docs
- API examples
- contributor guidance

Chinese is acceptable for temporary design discussion with the current user, but
commit-worthy repository material should remain English by default.

## 8. Python And Runtime Rules

Diego is primarily a Python service with a small Node dependency surface.

Python rules:

- use 4-space indentation and PEP 8 naming
- add type hints on public interfaces and important domain boundaries
- prefer dataclasses or Pydantic models where contracts benefit from explicit shape
- keep blocking I/O and subprocess behavior visible and reviewable
- do not hide environment-dependent behavior in implicit globals

Node / JS rules:

- `pptxgenjs` is a runtime dependency for slide compilation contracts
- generated slide JS should follow the expected export and API contract checks
- do not loosen JS contract validation just to pass a single bad generation case

Compatibility rules:

- old import paths such as `service.app` and `service.llm_client` are shims
- do not build new features on top of shim paths when the canonical path exists
- if you touch a shim, preserve migration intent and keep it thin

## 9. Tests And Validation

Before and after meaningful changes, use the relevant subset of:

```bash
git status --short
pytest
```

Useful focused commands:

```bash
pytest tests/integration/test_api_runs.py
pytest tests/integration/test_template_mode.py
pytest tests/integration/test_slide_preview_api.py
pytest tests/service/test_llm_resilience.py
pytest tests/service/test_quality_gate_hard_only.py
```

Useful local run commands:

```bash
python -m pip install -e .[dev]
npm install
python scripts/run_dev.py
```

When changing runtime behavior, validate the closest affected contracts:

- run creation and status retrieval
- outline confirmation behavior
- SSE event flow
- scratch artifact generation
- template mode behavior
- PPTX download and preview endpoints
- failure-path error codes and retryability

## 10. Documentation Duties

If you change service contracts, update the nearest canonical document:

- goals and acceptance baseline: `docs/PROJECT_GOALS.md`
- architecture and layering: `docs/ARCHITECTURE.md`
- future Spectra integration boundary: `docs/SPECTRA_CHANGE_POINTS.md`
- operational usage and commands: `README.md`

If a contract change affects API behavior, also update or add tests.

Keep the existing `refrences` spelling unless a dedicated rename change is
explicitly approved.

## 11. Commit Guidance

Use commit messages in this form:

- `type(scope): short summary`

Examples:

- `feat(api): add pptx artifact download endpoint`
- `refactor(run): split quality repair service from orchestrator`
- `test(template): cover slot mapping conflict path`

PR-quality changes should usually include:

- what changed and why
- validation commands run
- backward-compatibility notes when contracts changed
