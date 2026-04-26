# Interaction Schema Primitive Boundary Review

## Current Status

`interaction_schema_generation` is still a pressure candidate, not a promoted
Diego primitive.

The current pressure signal is still not broad enough, but it is no longer only
one sample:
- one bubble-sort-like sample shows that Diego may eventually need a generic
  way to emit state, transition, checkpoint, and trace-oriented content
- one water-cycle-like sample shows similar process-trace pressure in a
  non-algorithm domain
- both samples still sit too close to trace-shaped content and do not yet prove
  that Diego needs a separately promoted top-level primitive

## Recommendation

Do not promote yet.

More specifically:
- do not promote `interaction_schema_generation` as a separate top-level Diego
  primitive yet

Reason:
- the current evidence is enough to justify documentation-level interest
- it is not enough to prove a reusable Diego primitive beyond one
  algorithm-trace-shaped pressure sample
- promoting now would risk smuggling animation or workbench semantics into
  Diego under generic-looking names

## Relationship To Existing Taxonomy

This candidate overlaps with `sequence_or_script_plan`, and current evidence
supports treating that broader name as the primary Diego direction.

Current naming decision:
- `sequence_or_script_plan` is the broader sequence-planning direction
- `interaction_schema` is one candidate output shape beneath that broader
  direction
- `interaction_schema_generation` should not yet become the top-level Diego
  primitive name

Until broader pressure appears, prefer keeping this area under
`sequence_or_script_plan` rather than promoting a separate primitive family.

## Algorithm Trace Judgment

`algorithm_trace` should not be promoted as a generic Diego domain-model kind
at this stage.

Better reading:
- `algorithm_trace` is a pressure-sample subtype
- `process_trace` is a pressure-sample subtype
- if Diego later promotes an interaction-schema primitive, `algorithm_trace`
  and `process_trace` may become example shapes
- it should not define Diego ontology before non-algorithm pressure exists

## Minimum Later Shape If Promotion Becomes Justified

If later promotion becomes justified, the minimum provisional primitive shape
should stay generic and thin:

- input:
  - `generation_goal`
  - `source_scope`
  - `evidence_refs`
  - `constraints`
  - `requested_output_shape`
- output:
  - `schema_version`
  - `content_kind`
  - `states`
  - `transitions`
  - `inputs`
  - `checkpoints`
  - `trace`
  - `revision_targets`
  - `source_refs`
  - `warnings`

This would still be a Diego generation contract, not a runtime, renderer, or
shell contract.

## Remaining Pressure Samples Required

At least one more non-algorithm sample is required before promotion beyond the
current active-pressure stage.

The next sample should prove that the same generic shape helps outside
algorithm-step narration, for example:
- interaction flow explanation with explicit state changes
- branching procedural guidance with checkpoints and bounded inputs
- source-conditioned simulation or walkthrough content where state and
  transitions matter but no animation renderer is implied

If the next sample only needs ordered steps, then `sequence_or_script_plan` is
likely enough and no separate interaction-schema primitive should be promoted.

## Forbidden Ownership

Diego must not absorb ownership of:
- GIF
- PPTX step deck
- HTML preview
- Rive
- Remotion
- Pagevra materialization
- animation-card ontology
- shell or workbench semantics
