# Structured Content Generation Primitive Taxonomy

Status: `active design`

Purpose: define Diego's non-PPT abstraction axis as source-conditioned structured
content generation, not as product modes or downstream artifact formats.

## Reading Rule

Diego should be understood as a generation authority that can produce structured
content objects from source material and bounded generation goals.

The non-PPT axis is not:

- consumer workflow names
- markdown, html, docx, or preview ownership
- formal artifact persistence
- shell orchestration

The non-PPT axis is:

- source-conditioned input
- structured content object output
- explicit lifecycle and failure truth
- bounded revision over Diego-owned content objects

## Current Taxonomy

| Primitive family | Role | Status | Current or expected output | Outside Diego |
| --- | --- | --- | --- | --- |
| `generation_result` | umbrella result truth for Diego-owned generation runs | `canonical now` | lifecycle, trace, stage timing, warnings, generation outputs | formal artifact truth, shell state |
| `generic_content_object_output` | lightweight structured content objects usable by downstream consumers | `canonical now` | `content_blocks_v1` and adjacent generic object metadata | markdown, html, docx, preview |
| `retrieval_conditioned_input` | optional evidence/source scope used to condition generation | `canonical now` | source ids, grounded snippets, citation references when available | retrieval engine truth, source browser policy |
| `draft_package` | source-conditioned sectioned drafting lifecycle | `provisional but valid` | plan, sectioned draft, content blocks, citations, revision targets | rendering, compile/export, artifact persistence |
| `section_revision` | bounded revision of Diego-owned draft sections | `provisional but valid` | revised section content and draft version update | editor merge policy, shell anchor mapping |
| `structure_expansion` | expands a selected structure unit into child candidates or local summaries | `provisional implementation` | candidate units, local summaries, source refs, revision hints | graph editing, graph layout, artifact lineage |
| `item_generation` | generates reusable item-like content objects | `provisional implementation` | item stems, options or expected responses, explanations, source refs | scoring flow, answer UI, grading truth |
| `sequence_or_script_plan` | generates ordered sequence-aware plans and may later emit `interaction_schema` as one output shape when justified | `active pressure` | ordered units, transition notes, checkpoints, and trace-oriented outputs when justified | media runtime, playback, preview/export |

## Conceptual Handoff Direction

This taxonomy points toward a future neutral generation surface, but it does not
freeze a new wire format in this round.

In other words, this taxonomy does not freeze a new wire format.

Input concepts should stay generic:

- `generation_goal`
- `source_scope`
- `evidence_refs`
- `constraints`
- `anchor_context`
- `requested_output_shape`

Returned output concepts should stay generation-centered:

- `schema_version`
- `content_kind`
- `units`
- `anchors`
- `source_refs`
- `revision_targets`
- `warnings`

For sequence-aware pressure specifically:

- prefer `sequence_or_script_plan` as the broader primitive direction
- treat `interaction_schema` as one possible output shape beneath that broader
  direction when state, transition, input, checkpoint, and trace objects are
  genuinely needed
- do not promote `algorithm_trace` or `process_trace` into Diego ontology on
  their own

## Current Public Surface Reading

`/v1/content/runs` remains a provisional but valid implementation family for
`draft_package`, `structure_expansion`, and `item_generation`.

It may be consumed today for generic structured-content generation, but it
should not be treated as the final unified non-PPT transport shape.

## Promotion Rule

A primitive may move closer to public contract only when:

1. it can be named without a consumer workflow label
2. its output is a Diego-owned generation object
3. downstream render/export/formal-state work remains outside Diego
4. at least two pressure samples need the same shape
5. tests or docs guards prevent product-mode naming from entering Diego

## Do Not Do

Do not add product-specific public endpoints, schemas, or modes to represent
downstream consumers.

Do not make Diego emit markdown as primary truth.

Do not make Diego own html/docx render, preview, export, grading, graph editing,
media runtime, shell routing, or formal artifact semantics.
