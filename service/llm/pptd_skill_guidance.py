from __future__ import annotations

PPTD_SKILL_WORKFLOW_GUIDANCE = """
PPTD-first presentation workflow:
- Analyze language, audience, purpose, source material, page-count request, and visual constraints before planning slides.
- Choose a visual mode: reference, creative, or template. Without explicit template/reference input, use creative mode.
- Choose a content mode: summary, outline, or search. If the user only provides a topic, build a substantive search-style course/report outline.
- Plan design and content before authoring pages. Treat the design plan and outline as durable project artifacts.
- Prefer 12-18 pages for a normal complete deck when the user does not explicitly request a smaller count; if a count is provided, respect it.
- Use cover, contents or section framing, varied content layouts, and a final synthesis page when the slide count allows it.
- Keep every page specific and useful. Avoid generic filler, repeated adjacent layouts, and vague bullets.
- Use evidence/source notes when source material exists, so the resulting deck can trace claims back to references.
""".strip()


PPTD_VISUAL_QUALITY_GUIDANCE = """
PPTD visual quality constraints:
- Avoid default blue/purple AI-looking palettes unless the user explicitly asks for them or the topic truly requires them.
- Pick a coherent visual temperature, primary color, background, text color, and restrained accent color.
- Use strong title/body hierarchy. Body text should normally remain readable at 18-22px.
- Use grid alignment, consistent margins, and balanced body-area density.
- Do not use empty decorative placeholders as substitutes for real visual structure.
- For courseware and academic/report decks, favor calm professional layouts with clear diagrams, tables, timelines, and comparison structures.
- For PPTD elements, plan enough room for Chinese text: line height is closer to fontSize x 1.3 than the declared lineHeight alone.
- For education/courseware decks, content pages should use white or light backgrounds for projector readability; reserve dark backgrounds for cover, section, or emphasis pages.
- Treat diagrams, flowcharts, comparison tables, and case cards as comprehension tools, not decoration.
""".strip()


PPTD_OUTLINE_QUALITY_GUIDANCE = """
PPTD outline quality constraints:
- Page titles should be presentation-ready, short, and concrete.
- For education/courseware decks, each page title should state the knowledge point or conclusion, not only name a chapter.
- Keep one main topic per page. If a page contains two unrelated topics, split or reframe it as a comparison/process page.
- Content bullets should be directly usable on slides: 3-6 bullets for dense content pages, fewer bullets for cover/section/final pages.
- Include page_type and layout_hint that match the page's communicative job.
- Prefer information architecture over decorative wording: definitions, mechanisms, examples, comparisons, risks, processes, and conclusions.
- If the deck is educational, include learning objectives, key concepts, mechanism explanation, examples/practice, and summary.
- For abstract concepts, plan a visual explanation: mechanism diagram, shape-based flow, comparison matrix, or case card. Do not leave the page as a pure text list.
- If the deck is a report, include context, problem, evidence, analysis, decision, risks, and next actions.
- Treat bullets as a PPTD page plan, not prose paragraphs. Each bullet should be short enough to become one visible text block.
- For content-comparison pages, structure bullets with explicit group labels such as "GBN:" and "SR:" or "方案A:" and "方案B:", followed by 2-3 concrete points per group and one judgment/selection point.
- For content-timeline pages, use 3-5 ordered mechanism or process steps. Each step should look like "step label: action/result".
- For content-stat-callout pages, include concrete metrics or a compact markdown table, for example "| 指标 | GBN | SR |" plus short row bullets.
- For content-two-column or content-showcase pages, use two or three distinct concept blocks rather than repeating the same generic wording.
- Avoid adjacent pages that repeat the same bullet frame such as "定义/特点/应用" unless the source material requires it.
- Chinese bullets should normally stay under 32 characters; split long clauses into separate bullets.
""".strip()
