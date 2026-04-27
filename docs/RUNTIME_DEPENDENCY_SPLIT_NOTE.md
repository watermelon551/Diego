# Runtime Dependency Split Note

## Current Position

Diego keeps several runtime dependencies because they still belong to current
service behavior:

- Node + `pptxgenjs` for PPT compile and preview-adjacent generation paths
- `markitdown[pptx]` for template QA, extraction, and validation paths
- `asyncpg` for the postgres-backed run store

These dependencies should not be removed blindly just to shrink Docker.

## Possible Later Split

If future deployment pressure justifies it, Diego could later separate runtime
concerns into optional layers:

- base generation runtime
  - core run orchestration
  - outline and slide generation
  - non-template generation contracts
- template and QA runtime
  - template-mode validation
  - `markitdown[pptx]` dependent checks
- postgres store runtime
  - `asyncpg`
  - postgres-only persistence path

## Constraints

- missing `markitdown` must not silently succeed
- Node removal is not acceptable while PPT compile contracts still depend on it
- postgres support must remain explicit rather than implicitly degraded
- Docker slimming should follow architecture clarity, not replace it
