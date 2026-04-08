# Repository Guidelines

## Project Structure & Module Organization
This repository is currently documentation-first. Keep changes aligned with the existing layout:

- `docs/`: source of truth for product goals and service contracts (`PROJECT_GOALS.md`, `ARCHITECTURE.md`, `SPECTRA_CHANGE_POINTS.md`).
- `service/`: implementation area for the microservice (currently scaffolded/empty).
- `scripts/`: local automation helpers (generation, validation, tooling glue).
- `tests/`: automated tests for service behavior and contract checks.
- `refrences/`: reference material directory (keep existing name unless a dedicated rename PR is approved).

When adding code, organize by capability (for example, `service/api`, `service/state_machine`, `service/compile`).

## Build, Test, and Development Commands
No official build pipeline is committed yet. Use these baseline commands while contributing:

- `rg --files`: quick inventory of tracked files.
- `Get-ChildItem -Recurse -File`: verify workspace contents, including untracked files.
- `git status`: confirm clean/expected working tree before and after edits.
- `git log --oneline`: inspect local commit history.

If you introduce runtime code, include runnable commands in `README.md` (for example, service start and test commands) in the same PR.

## Coding Style & Naming Conventions
- Markdown docs: concise sections, stable terminology, and contract names that match `docs/ARCHITECTURE.md`.
- Python (when added): 4-space indentation, PEP 8 naming (`snake_case` for functions/modules, `PascalCase` for classes), and type hints on public interfaces.
- File naming: tests should mirror module names (example: `tests/test_state_machine.py` for `service/state_machine.py`).

## Testing Guidelines
There is no committed test framework yet. New feature PRs should add tests under `tests/` and document execution steps.

Minimum expectation for service code:
- state transition tests for run lifecycle,
- API contract tests for `/v1/ppt/runs*`,
- failure-path tests for retry/error-code behavior.

## Commit & Pull Request Guidelines
As of 2026-04-08, this repository has no commit history on `master`, so no existing convention can be inferred.

Adopt this format going forward:
- `type(scope): short summary` (example: `feat(api): add outline confirm endpoint contract`).

PRs should include:
- what changed and why,
- linked issue/task ID,
- validation evidence (commands run, sample request/response, or doc diff rationale),
- backward-compatibility notes for contract changes.