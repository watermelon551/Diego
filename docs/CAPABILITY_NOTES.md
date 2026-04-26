# Capability Notes

## Structure Expansion Assessment

Assessment conclusion:
- A reusable Diego primitive likely exists: `source-conditioned structure expansion`.

What it does:
- Given a selected structure unit plus optional source snippets, Diego can propose a small set of child concepts and short summaries for each child.
- The output stays generic: candidate labels, local summaries, and source references.

Why it is host-agnostic:
- The primitive operates on content structure, not on any specific editor, card, or artifact shell.
- The same behavior could support graph-like expansion, deeper outline branching, or concept breakdown in other hosts.

Why it is not a dedicated mode:
- Diego would not own graph editing semantics, selection binding, layout, interaction workflow, or artifact persistence.
- Diego would only own the generation step that expands one structure unit into grounded child candidates.

What remains in shell or workbench:
- selection and anchor semantics
- edit and merge behavior
- graph rendering and interaction
- artifact storage and lifecycle

Current decision:
- document the primitive candidate only
- do not add public API, product ontology, or graph-specific contracts yet
