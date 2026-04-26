# Minimal Consumer Shape Note

## A Generic Consumer Of Diego

A minimal generic consumer gives Diego:
- a topic or prompt
- a project scope
- optional retrieval source identifiers
- optional plan feedback or bounded revision instructions

It expects back:
- explicit lifecycle state
- a Diego-owned generation result
- lightweight structured content objects such as `content_blocks_v1`
- grounded plan, draft, and revision data when the primitive supports them
- explicit failure information when generation does not succeed

It does not expect Diego to own:
- product workflow state
- card or tool ontology
- shell routing or controller glue
- anchor mapping semantics
- preview, render, export, or compile truth for non-PPT content
- formal artifact truth

## Why This Pressure Matters

This consumer shape is intentionally small.

It helps keep Diego readable as a reusable primitive authority rather than a product-mode backend:
- the input shape stays generic
- the output shape stays generation-centered
- downstream projection responsibilities stay outside Diego
