# Cross-Consumer Primitive Assessment

## Shared Generation-Side Pressure

Three different artifact-first consumer directions currently create useful pressure:
- a long-form document-style consumer
- an item-oriented consumer
- a structure-oriented consumer

The useful question is not whether Diego should own those modes.
The useful question is whether a shared generation-side primitive is real.

## Primitive Assessment

| Primitive direction | Assessment | Reason |
| --- | --- | --- |
| `source-conditioned long-form drafting` | shared primitive seems real | A document-style consumer clearly benefits, and the same drafting package could support other rich text-like artifact consumers. |
| `item/question drafting` | shared primitive seems plausible but not settled | The pressure is real, but Diego still lacks a generic item contract that is independent from grading, answer flow, and host runtime. |
| `concept decomposition / structure expansion` | shared primitive seems real but still provisional | A structure-oriented consumer would benefit, and the same expansion logic could support non-graph decomposition workflows too. |
| `evidence-conditioned expansion inputs` | shared primitive seems real | Retrieval-conditioned inputs already generalize across drafting and expansion tasks. |
| `content-block package generation` | shared primitive seems real | Multiple consumers can translate a generic content-block package into local artifact shapes without forcing Diego to emit host-specific formats. |

## Rejection Rule

Rejected direction:
- hidden consumer modes inside Diego

Why:
- they would only rename host workflows as if they were Diego ontology
- they would make Diego own downstream semantics that are not reusable enough
