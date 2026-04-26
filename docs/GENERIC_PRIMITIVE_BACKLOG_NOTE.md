# Generic Primitive Map Note

## Current Assessment

Diego should strengthen or document only primitives that remain reusable across hosts and artifact shells.

| Primitive | What it does | Why it is generic | What it does not own | Status |
| --- | --- | --- | --- | --- |
| `source-conditioned long-form drafting` | turns topic, scope, retrieval inputs, plan, draft, and revision into a host-agnostic drafting lifecycle | it is defined by drafting semantics, not by any one editor or workflow shell | markdown render, preview, export, shell workflow state | `provisional but valid` |
| `grounded revision / section revision primitives` | applies bounded revision to Diego-owned draft sections while preserving lifecycle and grounding truth | the same revision behavior can be reused in multiple hosts for Diego-owned content objects | editor-local anchor models, ad hoc patch formats, shell-controlled merge semantics | `provisional but valid` |
| `retrieval-conditioned drafting inputs` | accepts optional retrieval source scope and grounded snippets as drafting inputs | retrieval-conditioned input shaping is reusable across drafting tasks | retrieval engine truth, source browser truth, library return policy | `canonical now` |
| `generic content-object outputs` | returns lightweight structured content objects such as `content_blocks_v1` | the output shape is not tied to markdown, docx, preview, or host rendering | render truth, export truth, formal artifact truth | `canonical now` |
| `draft_package` | names the current sectioned plan plus draft plus revision handoff in a neutral way | it describes Diego's source-conditioned drafting output rather than a consumer artifact | markdown render, compile/export, formal artifact truth | `provisional but valid` |
| `structure_expansion` | expands one selected structure unit into grounded child candidates and local summaries | it operates on structure semantics rather than any graph or shell product | graph editing semantics, selection anchor mapping, artifact persistence | `provisional implementation` |
| `item_generation` | generates reusable item-like outputs with grounding and explanation fields | it is defined by generic item content rather than any one host runtime or evaluation flow | scoring flow, answer UI, session runtime, controller glue | `provisional implementation` |
| `source-bound note drafting` | would produce grounded note-like drafting output from bounded source scope | it could be generic if note content is separated from projection and layout concerns | presentation shape, export shape, host note surfaces | `promising but premature` |
| `sequence_or_script_plan` | would generate ordered sequence-aware plans and may later emit `interaction_schema` as one output shape | bubble-sort `algorithm_trace` and water-cycle `process_trace` both suggest reusable sequence-aware pressure beyond one host artifact | media runtime, playback, preview/export, shell workflow state | `active pressure` |
| `scene/storyboard expansion` | would expand a content unit into sequential scene candidates | today it still attracts media, playback, preview, and runtime assumptions | preview truth, playback semantics, render/export truth | `keep in shell/workflow for now` |
| `interaction-prototype content expansion` | would generate structured content for downstream interactive runtimes | current semantic center is still runtime behavior, not Diego-owned generation truth | interaction state machine truth, event runtime, execution semantics | `keep in shell/workflow for now` |

## Reading Rule

- `canonical now` means the primitive family is already part of Diego's settled ownership boundary.
- `provisional but valid` means the direction is real and implemented or documented, but not yet fully canonized as settled top-level Diego surface.
- `promote next` means the taxonomy is generic enough to clarify now, while transport and public contract can wait.
- `provisional implementation` means Diego now ships a real generic implementation, but the public transport and long-term canon remain explicitly provisional.
- `active pressure` means Diego has meaningful multi-sample pressure and should keep refining the primitive boundary, but should not freeze a stable public API yet.
- `later backlog` means the shape is plausible but still too close to runtime or presentation concerns.
- `promising but premature` means the idea may belong in Diego later, but the contract is not yet generic enough.
- `keep in shell/workflow for now` means the current semantic center remains outside Diego.
