from __future__ import annotations

import re
from pathlib import Path

from ...models import OutlineNode
from ...run.types import ChartFact, ChartPlan


def build_chart_plan_from_bullets(*, node: OutlineNode, source_refs: list[str]) -> ChartPlan:
    facts = extract_chart_facts(node=node, source_refs=source_refs)
    if facts:
        labels = [item.label for item in facts[:6]]
        values = [item.value for item in facts[:6]]
        unit = facts[0].unit
        return ChartPlan(
            has_verified_data=True,
            mode="quantitative",
            labels=labels,
            values=values,
            unit=unit,
            note="",
            source="outline_facts",
        )
    labels = [item[:28] for item in (node.bullets[:5] or [node.title])]
    return ChartPlan(
        has_verified_data=False,
        mode="qualitative_fallback",
        labels=labels,
        values=[1.0 for _ in labels],
        unit="",
        note="Qualitative trend view; quantitative values not supplied in source bullets.",
        source="qualitative_fallback",
    )


def extract_chart_facts(*, node: OutlineNode, source_refs: list[str]) -> list[ChartFact]:
    facts: list[ChartFact] = []
    colon_re = re.compile(
        r"(?P<label>[^:]{1,60})[:]?\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|k|m|b)?",
        flags=re.IGNORECASE,
    )
    unit_re = re.compile(
        r"(?P<label>[^0-9]{1,60}?)(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|k|m|b)?",
        flags=re.IGNORECASE,
    )
    source = source_refs[0] if source_refs else "user_outline"
    for bullet in node.bullets:
        text = bullet.strip()
        if not text:
            continue
        if re.fullmatch(r"point\s+\d+(?:\.\d+)?", text, flags=re.IGNORECASE):
            continue
        match = colon_re.search(text)
        if not match:
            match = unit_re.search(text)
        if not match:
            continue
        label = match.group("label").strip(" -:") or node.title
        raw_value = match.group("value")
        try:
            value = float(raw_value)
        except ValueError:
            continue
        unit = (match.group("unit") or "").strip()
        facts.append(
            ChartFact(
                label=label[:40],
                value=value,
                unit=unit,
                source_ref=source,
            )
        )
    return facts


def rewrite_related_chart_xml(
    *,
    unpacked: Path,
    slide_xml: Path,
    node: OutlineNode,
    chart_plan: ChartPlan,
    parse_xml_attrs,
    rewrite_chart_xml_content,
) -> dict[str, object]:
    rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
    if not rels_path.exists():
        return {
            "has_chart_slot": False,
            "has_verified_data": chart_plan.has_verified_data,
            "mode": "none",
            "source": chart_plan.source,
        }
    rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
    chart_targets: list[str] = []
    for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
        attrs = parse_xml_attrs(tag)
        rel_type = attrs.get("Type", "")
        target = attrs.get("Target", "")
        if rel_type.endswith("/chart") and target:
            chart_targets.append(target)
    if not chart_targets:
        return {
            "has_chart_slot": False,
            "has_verified_data": chart_plan.has_verified_data,
            "mode": "none",
            "source": chart_plan.source,
        }
    report = {
        "has_chart_slot": True,
        "has_verified_data": chart_plan.has_verified_data,
        "mode": chart_plan.mode,
        "source": chart_plan.source,
        "note": chart_plan.note,
        "labels": chart_plan.labels,
    }
    for target in chart_targets:
        chart_path = (slide_xml.parent / target).resolve()
        try:
            chart_path.relative_to(unpacked.resolve())
        except ValueError:
            continue
        if not chart_path.exists():
            continue
        chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
        chart_xml = rewrite_chart_xml_content(
            chart_xml=chart_xml,
            node=node,
            chart_plan=chart_plan,
        )
        chart_path.write_text(chart_xml, encoding="utf-8")
    return report


def rewrite_chart_xml_content(
    *,
    chart_xml: str,
    node: OutlineNode,
    chart_plan: ChartPlan,
    xml_escape,
    rewrite_chart_cache_points,
) -> str:
    chart_xml = re.sub(
        r"<a:t>.*?</a:t>",
        f"<a:t>{xml_escape(node.title)}</a:t>",
        chart_xml,
        count=1,
        flags=re.DOTALL,
    )
    categories = chart_plan.labels[:5] or [node.title]
    values = [str(value).rstrip("0").rstrip(".") for value in chart_plan.values[: len(categories)]]
    if len(values) < len(categories):
        values.extend(["1" for _ in range(len(categories) - len(values))])
    chart_xml = rewrite_chart_cache_points(
        chart_xml=chart_xml,
        cache_tag="c:strCache",
        value_tag="c:v",
        values=categories,
    )
    chart_xml = rewrite_chart_cache_points(
        chart_xml=chart_xml,
        cache_tag="c:numCache",
        value_tag="c:v",
        values=values,
    )
    return chart_xml


def rewrite_chart_cache_points(
    *,
    chart_xml: str,
    cache_tag: str,
    value_tag: str,
    values: list[str],
    xml_escape,
) -> str:
    pattern = rf"<{cache_tag}>[\s\S]*?</{cache_tag}>"

    def repl(match: re.Match[str]) -> str:
        block = match.group(0)
        pt_pattern = re.compile(rf"<c:pt\b[^>]*idx=\"(\d+)\"[^>]*>[\s\S]*?<{value_tag}>.*?</{value_tag}>[\s\S]*?</c:pt>")
        pts = list(pt_pattern.finditer(block))
        if not pts:
            return block
        out: list[str] = []
        cursor = 0
        for idx, pt in enumerate(pts):
            out.append(block[cursor:pt.start()])
            value = values[idx] if idx < len(values) else values[-1]
            out.append(
                re.sub(
                    rf"<{value_tag}>.*?</{value_tag}>",
                    f"<{value_tag}>{xml_escape(value)}</{value_tag}>",
                    pt.group(0),
                    flags=re.DOTALL,
                )
            )
            cursor = pt.end()
        out.append(block[cursor:])
        rebuilt = "".join(out)
        rebuilt = re.sub(
            r"<c:ptCount\b[^>]*/>",
            f'<c:ptCount val="{len(pts)}"/>',
            rebuilt,
            count=1,
        )
        return rebuilt

    return re.sub(pattern, repl, chart_xml)
