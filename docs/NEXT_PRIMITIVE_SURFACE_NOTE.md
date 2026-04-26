# Next Primitive Surface Note

## Concrete Next Primitive Direction

The next Diego primitive direction should stay generation-centered:
- `source-conditioned draft package`

This is a conceptual primitive direction, not a commitment to a final new wire format.

## Owner-Owned Concepts

Diego should own:
- generation result
- source-conditioned drafting inputs
- plan truth
- structured draft truth
- section/block revision truth
- grounding and citation truth for Diego-owned drafts
- explicit lifecycle and failure truth

## Accepted Input Concepts

The next primitive direction should continue to accept:
- topic or prompt
- project scope
- optional retrieval source identifiers
- bounded planning hints such as audience, purpose, and tone
- bounded revision instructions against Diego-owned draft units

## Returned Output Concepts

The next primitive direction should continue returning:
- structured draft output
- lightweight generic content objects such as `content_blocks_v1` or a compatible successor
- sectioned draft shape
- citation and grounding references
- explicit lifecycle state
- explicit failure information

## Failure And Validation Expectations

Expected behavior:
- invalid or incomplete draft structure should fail explicitly
- revision conflicts should remain explicit
- grounding loss should not be silently hidden behind synthetic success
- normalization may repair contract drift, but must not blur ownership or failure truth

## What Remains Outside Diego

The following remain outside owner responsibility:
- markdown formatting
- document compile/export
- grading semantics
- graph editing semantics
- source-binding UI semantics
- refine anchor UI semantics
- artifact persistence and formal state
- shell orchestration semantics

## Why This Is The Right Next Surface

This direction is concrete enough for later thin shell consumption because it gives a downstream consumer:
- stable generation-side structure
- reusable grounding semantics
- bounded revision behavior

But it still avoids freezing Diego into product ontology or a single host presentation format.
