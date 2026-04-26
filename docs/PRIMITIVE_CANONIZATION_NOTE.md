# Primitive Canonization Note

## Current Canonical Reusable Primitive Surfaces

Diego currently has two canonical reusable primitive families:
- PPT generation orchestration
- generic content-object output for Diego-owned generation results

These are canonical because their ownership, lifecycle, and output boundaries are already explicit in the repo.

## What Diego Already Owns Cleanly

Diego already owns, in generic authority language:
- `generation result`
- `structured draft output`
- long-form/content generation as a valid Diego direction
- source-conditioned generation where grounding materially improves generation truth

Diego does not need product-mode naming to own these responsibilities.

## Current Provisional Surface

`/v1/content/runs` and `/v1/content/runs/prompt` are provisional but valid.

They are the current Diego public surface for the generic capability named:
- `source-conditioned long-form drafting`

This surface is a real implementation direction, not an experiment to discard.
But it is not yet fully canonized as Diego's settled top-level generic primitive surface.

Consumer reading rule:
- a generic consumer may already rely on this surface as a valid Diego drafting capability
- but it should not yet assume this transport is the final settled long-term non-PPT surface

## Why The Long-Form Surface Is Still Provisional

The current implementation is healthy, test-covered, and semantically aligned with Diego's direction.

It remains provisional because controller-side canonization has not yet declared all of the following fully settled:
- the exact scope of Diego's non-PPT primitive family
- the long-term canonical primitive map around drafting, revision, and adjacent growth
- the allowed future expansion boundary for this surface

## What The Long-Form Surface Means Today

The provisional long-form surface represents:
- source-aware planning
- plan confirmation
- structured draft generation
- grounded section-aware revision
- generic content-object output

Its current Diego-owned output remains:
- `content_blocks_v1`

The current neutral reading of this surface is:
- `draft_package`

That means the surface currently produces plan, sectioned draft, content blocks,
citations, revision targets, lifecycle state, and failure truth. It does not
settle Diego's final unified non-PPT transport.

## What Is Canonical In The Long-Form Direction

Even while the public surface remains provisional, the following semantic points are already canonical:
- Diego may own host-agnostic drafting truth
- Diego may return lightweight generic content objects
- Diego may own grounded revision semantics for Diego-owned drafts
- Diego may own structured draft output without owning downstream render formats
- Diego does not need markdown, preview, docx, export, or shell workflow truth to succeed

## What Is Not Settled Yet

The following should not be treated as fully settled:
- whether the current `/v1/content/*` surface is the final long-term transport shape
- whether future adjacent primitives should extend this surface or remain separate
- whether additional non-PPT primitives should be promoted into public Diego contracts now

The next adjacent taxonomy directions are:
- `structure_expansion`
- `item_generation`
- `sequence_or_script_plan`

Current implementation note:
- `structure_expansion` and `item_generation` now exist as provisionally implemented structured-content primitives under the current `/v1/content/runs` family
- their existence does not promote `/v1/content/runs` from provisional to canonical
- their current transport should still be read as useful Diego reality pending controller approval of the longer-term primitive map
- `sequence_or_script_plan` is now best read as an active-pressure direction rather than a settled primitive or public API
- `interaction_schema` should currently be read as one possible output shape beneath `sequence_or_script_plan`, not as a separate promoted top-level Diego primitive
- bubble-sort `algorithm_trace` and water-cycle `process_trace` are pressure-sample subtypes, not Diego ontology

These names describe generic generation-side content objects. They do not grant
Diego ownership over downstream render, grading, graph editing, media runtime,
shell routing, or formal artifact semantics.

## Expansion Rule

Future promotion from provisional to canonical is allowed only when:

1. the capability can be named in generic language without host product labels
2. the surface preserves explicit lifecycle, revision, and failure truth
3. the output stays a Diego-owned generation contract rather than a render, export, or shell contract
4. the feature is reusable beyond one host workflow
5. the controller-approved primitive map is explicit about what remains outside Diego
