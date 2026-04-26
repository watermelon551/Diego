# Structured Generation Primitive Status Note

## Purpose

This note is the owner-level status map for Diego as a generic
source-conditioned structured content generation authority.

It records what is already settled, what is provisionally usable, what is
under active pressure, and what must remain outside Diego ownership.

## Canonical Now

- `generation_result`
- `generic_content_object_output`
- `content_blocks_v1`
- `retrieval_conditioned_input`

These are canonical because Diego already owns their semantics, contract
boundaries, and validation pressure without relying on any one host workflow.

## Provisional But Valid

- `draft_package`
- `/v1/content/runs`
- source-conditioned long-form drafting
- section or block revision for Diego-owned drafts

These are real Diego surfaces and may be consumed today, but they should not be
treated as the final universal non-PPT API.

## Active Pressure

- `structure_expansion`
- `item_generation`
- `sequence_or_script_plan`

Current naming decision:
- use `sequence_or_script_plan` as the broader primitive direction
- treat `interaction_schema` as one possible output shape beneath that broader
  direction, not as a separate top-level Diego primitive yet

Pressure evidence:
- document pressure supports `draft_package`
- concept-decomposition pressure supports `structure_expansion`
- item-oriented pressure supports `item_generation`
- bubble-sort `algorithm_trace` and water-cycle `process_trace` both support
  sequence-aware structured generation pressure

Current interpretation:
- `algorithm_trace` is a pressure-sample subtype
- `process_trace` is a pressure-sample subtype
- neither should define Diego ontology on its own

## Later Backlog

- richer storyboard or scene expansion
- interaction runtime planning
- media-specific planning

These remain too close to runtime behavior, renderer assumptions, or host-local
materialization concerns.

## Do Not Own

Diego must not own:
- render or export truth
- PPTX step deck truth
- GIF truth
- HTML preview truth
- Pagevra materialization
- formal artifact state
- shell or workbench workflow
- card ontology
- Ourograph truth
- Rive or Remotion runtime semantics

## Promotion Rule

Promotion beyond active pressure is allowed only when:

1. the primitive can be named in generic language
2. the output stays a Diego-owned generation contract
3. at least two pressure samples need the same shape
4. downstream render, export, runtime, and formal-state work stay outside Diego
5. tests and docs guards keep host-product ontology out

## Current Recommendation

What is ready:
- canonical generic content-object output
- provisional drafting surface
- provisionally implemented structure and item generation

What remains provisional:
- `/v1/content/runs`
- `draft_package`
- `structure_expansion`
- `item_generation`

What needs one more pressure wave:
- `sequence_or_script_plan` as a broader primitive
- `interaction_schema` as one candidate output shape beneath it

The next useful pressure wave should include one more non-algorithm
sequence-aware sample so Diego can verify whether the same shape holds beyond
`algorithm_trace` and `process_trace`.
