"""Native two-page Durably company claim-risk report.

This module is called directly by app.py through build_company_report_pdf(data).
It intentionally uses only ReportLab, which is already present in requirements.txt.
The output is fixed to exactly two A4 pages and uses the live scan-result schema.
Page 2 follows a findings -> external context -> actions -> methodology sequence.
"""
from __future__ import annotations

import io
import re
from html import escape as _escape
from urllib.parse import urlparse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4
MARGIN_X = 13 * mm
MARGIN_TOP = 10 * mm
MARGIN_BOTTOM = 12 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

# Brand / report palette
NAVY = colors.HexColor("#173E52")
TEAL = colors.HexColor("#2C766B")
TEAL_DARK = colors.HexColor("#195A53")
GREEN = colors.HexColor("#2F7D55")
GREEN_SOFT = colors.HexColor("#EAF5EF")
AMBER = colors.HexColor("#A87311")
AMBER_SOFT = colors.HexColor("#FFF6DF")
RED = colors.HexColor("#AF3D43")
RED_SOFT = colors.HexColor("#FFF0F0")
BLUE_SOFT = colors.HexColor("#EFF5F8")
GREY_900 = colors.HexColor("#263238")
GREY_700 = colors.HexColor("#52616A")
GREY_500 = colors.HexColor("#7A8A93")
GREY_300 = colors.HexColor("#D8E1E5")
GREY_150 = colors.HexColor("#EDF1F3")
GREY_100 = colors.HexColor("#F7F9FA")
WHITE = colors.white


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=8.05, leading=10.3, textColor=GREY_700)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


ST = {
    "brand": _style("brand", fontName="Helvetica-Bold", fontSize=7.8, leading=9.2, textColor=TEAL_DARK),
    "title": _style("title", fontName="Helvetica-Bold", fontSize=20.5, leading=22, textColor=NAVY),
    "subtitle": _style("subtitle", fontSize=9.0, leading=11, textColor=GREY_700),
    "meta": _style("meta", fontSize=7.1, leading=8.9, textColor=GREY_700, alignment=TA_RIGHT),
    "meta_b": _style("meta_b", fontName="Helvetica-Bold", fontSize=6.6, leading=8, textColor=GREY_500, alignment=TA_RIGHT),
    "section": _style("section", fontName="Helvetica-Bold", fontSize=9.7, leading=11.4, textColor=NAVY, spaceBefore=4, spaceAfter=3),
    "body": _style("body", fontSize=8.0, leading=10.4, textColor=GREY_700),
    "body_dark": _style("body_dark", fontSize=8.0, leading=10.4, textColor=GREY_900),
    "small": _style("small", fontSize=7.8, leading=10.0, textColor=GREY_700),
    "small_dark": _style("small_dark", fontSize=7.8, leading=10.0, textColor=GREY_900),
    "tiny": _style("tiny", fontSize=6.25, leading=7.9, textColor=GREY_500),
    "quote": _style("quote", fontSize=7.8, leading=10.0, textColor=GREY_900, backColor=colors.HexColor("#FFFDF6")),
    "card_label": _style("card_label", fontName="Helvetica-Bold", fontSize=6.2, leading=7.5, textColor=TEAL_DARK),
    "card_num": _style("card_num", fontName="Helvetica-Bold", fontSize=19, leading=20, textColor=NAVY),
    "card_risk": _style("card_risk", fontName="Helvetica-Bold", fontSize=8.0, leading=9.2),
    "claim_title": _style("claim_title", fontName="Helvetica-Bold", fontSize=9.2, leading=11, textColor=NAVY),
    "claim_risk": _style("claim_risk", fontName="Helvetica-Bold", fontSize=8.2, leading=9.6, alignment=TA_RIGHT),
    "footer": _style("footer", fontName="Helvetica-Oblique", fontSize=5.25, leading=6.5, textColor=GREY_500),
}


def esc(value) -> str:
    return _escape(str(value if value is not None else ""), quote=False)


def clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_sentence(value: str, max_chars: int = 240) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    if match and match.start() <= max_chars:
        return text[: match.start() + 1]
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "."


def bounded_text(value, max_chars: int, suffix: str = ".") -> str:
    """Keep text within the fixed two-page format without showing visible ellipses."""
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + suffix


def risk_color(risk) -> colors.Color:
    text = str(risk or "").lower()
    if "high" in text:
        return RED
    if "medium" in text or "elev" in text or "mod" in text:
        return AMBER
    return GREEN


def risk_soft(risk) -> colors.Color:
    text = str(risk or "").lower()
    if "high" in text:
        return RED_SOFT
    if "medium" in text or "elev" in text or "mod" in text:
        return AMBER_SOFT
    return GREEN_SOFT


def risk_label_from_score(score) -> str:
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "Not assessed"
    if score >= 90:
        return "Very high"
    if score >= 75:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def is_material(claim: dict) -> bool:
    typ = str(claim.get("claim_type") or claim.get("type") or "").lower()
    return not (typ.startswith("no material") or typ.startswith("no major"))


def merge_claims(rows: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: dict[str, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict) or not is_material(raw):
            continue
        item = dict(raw)
        key = clean_text(item.get("claim_text") or item.get("claim") or "").lower()[:220]
        if key and key in seen:
            existing = seen[key]
            typ = item.get("claim_type") or item.get("type") or ""
            old = existing.get("claim_type") or existing.get("type") or ""
            if typ and typ not in old:
                existing["claim_type"] = old + " + " + typ
            terms = list(existing.get("problematic_terms") or [])
            for term in item.get("problematic_terms") or []:
                if term not in terms:
                    terms.append(term)
            existing["problematic_terms"] = terms
        else:
            merged.append(item)
            if key:
                seen[key] = item
    return merged


def combined_top_claims(data: dict, limit: int = 3) -> list[dict]:
    rows = list(data.get("claim_inventory") or data.get("findings") or [])
    if not rows:
        rows = list(data.get("green_findings") or []) + list(data.get("social_findings") or [])
    rows = merge_claims(rows)

    def ranking(item: dict):
        risk = str(item.get("risk_level") or item.get("risk") or "").lower()
        risk_rank = 3 if "very" in risk else 2 if "high" in risk else 1 if ("medium" in risk or "elev" in risk) else 0
        score = item.get("claim_score") or item.get("score") or 0
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0
        return (risk_rank, score)

    return sorted(rows, key=ranking, reverse=True)[:limit]


def claim_title(claim: dict) -> str:
    return clean_text(claim.get("claim_type") or claim.get("type") or "Sustainability claim")


def claim_risk(claim: dict) -> str:
    return clean_text(claim.get("risk_level") or claim.get("risk") or "Review")


def claim_source(claim: dict) -> str:
    source = clean_text(claim.get("source_label") or claim.get("source_url") or "Reviewed material")
    if source.startswith("http"):
        parsed = urlparse(source)
        if parsed.path and parsed.path != "/":
            filename = parsed.path.rsplit("/", 1)[-1]
            return filename or parsed.netloc
        return parsed.netloc.replace("www.", "")
    return source


def claim_excerpt(claim: dict, max_chars: int = 330) -> str:
    text = clean_text(claim.get("claim_text") or claim.get("claim") or "")
    phrase = clean_text(claim.get("matched_phrase") or "")
    if len(text) <= max_chars:
        return text
    if phrase:
        idx = text.lower().find(phrase.lower())
        if idx >= 0:
            start = max(0, idx - 120)
            end = min(len(text), idx + len(phrase) + 160)
            snippet = text[start:end].strip()
            if start > 0:
                snippet = "Context: " + snippet
            return bounded_text(snippet, max_chars)
    return bounded_text(text, max_chars)


def trigger_phrase(claim: dict) -> str:
    phrase = clean_text(claim.get("matched_phrase") or "")
    if phrase:
        return phrase
    terms = claim.get("problematic_terms") or []
    return clean_text(terms[0]) if terms else ""


def highlighted_excerpt(claim: dict, max_chars: int = 330) -> str:
    text = esc(claim_excerpt(claim, max_chars))
    phrase = trigger_phrase(claim)
    if not phrase:
        return text
    try:
        return re.sub(
            re.escape(esc(phrase)),
            lambda match: f'<b backColor="#FFF1A8">{match.group(0)}</b>',
            text,
            flags=re.IGNORECASE,
        )
    except re.error:
        return text


def why_text(claim: dict) -> str:
    raw = claim.get("why_flagged") or claim.get("risk_reason") or claim.get("issue")
    if raw:
        return bounded_text(raw, 245)
    phrase = trigger_phrase(claim)
    typ = claim_title(claim)
    if phrase:
        return f'The wording “{phrase}” was retained under the {typ.lower()} module and requires claim-specific substantiation.'
    return f"The wording was retained under the {typ.lower()} module and requires claim-specific review."


def evidence_gap_text(claim: dict) -> str:
    evidence = claim.get("evidence_needed")
    if isinstance(evidence, (list, tuple)) and evidence:
        return bounded_text("; ".join(str(x) for x in evidence[:4]), 205)
    if isinstance(evidence, str) and evidence:
        return bounded_text(evidence, 205)
    return "Scope, methodology, evidence date, verification basis and limitations."


def rewrite_text(claim: dict) -> str:
    raw = clean_text(claim.get("suggested_rewrite") or claim.get("rewrite") or "")
    if raw:
        return bounded_text(raw, 300)
    typ = claim_title(claim).lower()
    if "label" in typ or "certification" in typ:
        return "Name the scheme owner, criteria, independent verifier, audited scope and validity period, or clarify that the wording does not refer to independent certification."
    if "climate" in typ or "offset" in typ or "carbon" in typ:
        return "Separate actual emissions reductions from offsetting and disclose the boundary, baseline, methodology, residual emissions, offset use and reporting period."
    if "generic environmental" in typ:
        return "Specify the exact environmental attribute, product scope, comparison baseline, method, evidence, reporting period and limitations."
    return "Use precise, claim-specific wording and disclose scope, methodology, evidence, reporting period and limitations."


def compact_action(action: dict, company: str) -> tuple[str, str]:
    title = clean_text(action.get("title") or "Priority action")
    low = title.lower()
    who = company or "the company"
    if "green claims" in low or "empco" in low:
        return title, f"Review the exact consumer-facing environmental wording used by {who}. Confirm scope, product coverage, methodology, evidence, verification basis and limitations before reuse."
    if "social claims" in low:
        return title, f"For retained social claims, document stakeholder scope, KPIs, audit or workforce evidence, grievance and remedy arrangements, and clear limitations."
    if "forced" in low or "supplier" in low:
        return title, "Document supplier and product traceability, geography and product risk assessment, mitigation, grievance and remediation, and withdrawal or customs-response readiness."
    if "evidence file" in low:
        return title, "Create one evidence file per priority claim, including approved wording, source, owner, evidence link, review status, approval date and next review deadline."
    if "label" in low or "certification" in low:
        return title, "Confirm the scheme owner, criteria, scope, verification body, surveillance process and validity period for every label or certification referenced."
    raw = clean_text(action.get("action") or action.get("description") or "")
    return title, bounded_text(raw, 285) if raw else "Assign an owner, supporting evidence, review status and completion date."


def reviewed_sources(data: dict, limit: int = 3) -> list[str]:
    pages = list((data.get("report") or {}).get("pages_reviewed") or [])
    out: list[str] = []
    for value in pages:
        text = clean_text(value)
        if not text:
            continue
        if text.startswith("http"):
            parsed = urlparse(text)
            domain = parsed.netloc.replace("www.", "")
            filename = parsed.path.rsplit("/", 1)[-1]
            label = domain if not filename else f"{domain} · {filename}"
        else:
            label = text
        label = bounded_text(label, 105)
        if label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    if not out and data.get("source_label"):
        out.append(bounded_text(data.get("source_label"), 105))
    return out


def external_signals(data: dict, limit: int = 2) -> list[dict]:
    ext = data.get("external_research") or {}
    rows = []
    for branch in (ext.get("green") or {}, ext.get("social") or {}, ext):
        rows.extend(branch.get("targeted_negative_sources") or [])
    unique = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def company_name(data: dict) -> str:
    comp = data.get("company") or {}
    if isinstance(comp, dict):
        name = clean_text(comp.get("company") or comp.get("name"))
    else:
        name = clean_text(comp)
    return name if name and name.lower() != "company reviewed" else "Company"


def metadata(data: dict) -> dict:
    pages = list((data.get("report") or {}).get("pages_reviewed") or [])
    domains = set()
    for page in pages:
        parsed = urlparse(str(page))
        if parsed.netloc:
            domains.add(parsed.netloc.replace("www.", ""))
    assessment = "Internal document scan" if data.get("document_type") or "document" in str(data.get("assessment_type", "")).lower() else "Website scan"
    confidence = data.get("confidence") or {}
    context = data.get("entity_context_indicator") or {}
    return {
        "source": clean_text(data.get("source_label") or data.get("original_url") or "Reviewed material"),
        "date": clean_text(data.get("analysis_date") or "")[:10],
        "assessment": assessment,
        "coverage": f"{len(pages)} page(s) across {len(domains)} domain(s)" if pages else "Coverage not available",
        "confidence": clean_text(confidence.get("level") or "Not assessed"),
        "confidence_reason": bounded_text(" ".join(confidence.get("reasons") or []), 260) or "Confidence reflects source access, coverage and external-search availability.",
        "entity_level": clean_text(context.get("level") or "Not assessed"),
        "entity_note": bounded_text(context.get("note") or "Entity context is shown separately from claim-communication risk.", 230),
    }


def header_block(data: dict, page_subtitle: str) -> list:
    name = company_name(data)
    meta = metadata(data)
    left = [
        Paragraph("DURABLY SUSTAINABILITY SCAN", ST["brand"]),
        Spacer(1, 1.2 * mm),
        Paragraph(esc(name), ST["title"]),
        Paragraph(esc(page_subtitle), ST["subtitle"]),
    ]
    source = bounded_text(meta["source"], 75)
    right = [
        Paragraph("REVIEWED SOURCE", ST["meta_b"]),
        Paragraph(esc(source), ST["meta"]),
        Paragraph(f'{esc(meta["date"])} · {esc(meta["assessment"])}', ST["meta"]),
        Paragraph(esc(meta["coverage"]), ST["meta"]),
        Paragraph(f'Confidence: <b>{esc(meta["confidence"])}</b>', ST["meta"]),
    ]
    top = Table([[left, right]], colWidths=[CONTENT_W * 0.64, CONTENT_W * 0.36])
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    bar = Table([["", ""]], colWidths=[CONTENT_W * 0.74, CONTENT_W * 0.26], rowHeights=[3.0 * mm])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), NAVY),
        ("BACKGROUND", (1, 0), (1, 0), TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [bar, Spacer(1, 3.2 * mm), top, Spacer(1, 3.0 * mm)]


def section_title(text: str) -> Paragraph:
    return Paragraph(esc(text.upper()), ST["section"])


def summary_box(data: dict) -> Table:
    name = company_name(data)
    global_score = data.get("global_score", data.get("overall_score"))
    global_risk = data.get("global_risk", data.get("overall_risk")) or risk_label_from_score(global_score)
    claims = combined_top_claims(data, 3)
    areas = []
    for claim in claims:
        area = claim_title(claim)
        if area and area.lower() not in {a.lower() for a in areas}:
            areas.append(area)
    if areas:
        if len(areas) == 1:
            focus = areas[0].lower()
        else:
            focus = ", ".join(a.lower() for a in areas[:-1]) + " and " + areas[-1].lower()
        summary = f"The main retained issues concern {focus}."
    else:
        summary = "No material problematic claim signal was retained in the reviewed material."
    main = Paragraph(
        f'<b>Overall result: {esc(global_score)}/100 — {esc(global_risk)} claim risk.</b> {esc(summary)}',
        ST["body_dark"],
    )
    note = clean_text(data.get("fallback_note") or "Verify the reviewed entity and source scope before relying on this result.")
    note = bounded_text(note, 220)
    box = Table([[main, Paragraph(esc(note), ST["small"]) ]], colWidths=[CONTENT_W * 0.73, CONTENT_W * 0.27])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), AMBER_SOFT),
        ("BACKGROUND", (1, 0), (1, 0), GREY_100),
        ("LINEBEFORE", (0, 0), (0, 0), 3, AMBER),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, GREY_300),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return box


def score_card(label: str, value, risk: str, note: str = "") -> Table:
    color = risk_color(risk)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        number = f'{esc(value)}<font size="6.5" color="#7A8A93">/100</font>'
    else:
        number = esc(value or "—")
    rows = [
        [Paragraph(esc(label.upper()), ST["card_label"])],
        [Paragraph(number, ST["card_num"])],
        [Paragraph(esc(risk or "Not assessed"), ParagraphStyle("cr", parent=ST["card_risk"], textColor=color))],
    ]
    if note:
        rows.append([Paragraph(esc(bounded_text(note, 105)), ST["tiny"])])
    card = Table(rows, colWidths=[CONTENT_W / 4 - 3.5])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("LINEBEFORE", (0, 0), (0, -1), 2.8, color),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1.2),
    ]))
    return card


def score_row(data: dict) -> Table:
    meta = metadata(data)
    global_score = data.get("global_score", data.get("overall_score"))
    global_risk = data.get("global_risk", data.get("overall_risk")) or risk_label_from_score(global_score)
    green_score = data.get("green_score")
    green_risk = data.get("green_risk") or risk_label_from_score(green_score)
    social_score = data.get("social_score")
    social_risk = data.get("social_risk") or risk_label_from_score(social_score)
    cards = [
        score_card("Overall claims risk", global_score, global_risk),
        score_card("Green claims risk", green_score, green_risk),
        score_card("Social claims risk", social_score, social_risk),
        score_card("Entity context", meta["entity_level"], meta["entity_level"], meta["entity_note"]),
    ]
    table = Table([cards], colWidths=[CONTENT_W / 4] * 4)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def risk_driver_table(claims: list[dict]) -> Table:
    rows = [[
        Paragraph("#", ParagraphStyle("th1", parent=ST["tiny"], fontName="Helvetica-Bold", textColor=WHITE)),
        Paragraph("CLAIM AREA", ParagraphStyle("th2", parent=ST["tiny"], fontName="Helvetica-Bold", textColor=WHITE)),
        Paragraph("FLAGGED WORDING", ParagraphStyle("th3", parent=ST["tiny"], fontName="Helvetica-Bold", textColor=WHITE)),
        Paragraph("SOURCE", ParagraphStyle("th4", parent=ST["tiny"], fontName="Helvetica-Bold", textColor=WHITE)),
    ]]
    for idx, claim in enumerate(claims, 1):
        rows.append([
            Paragraph(str(idx), ST["small_dark"]),
            Paragraph(f'<b>{esc(bounded_text(claim_title(claim), 65))}</b><br/><font color="#7A8A93">{esc(claim_risk(claim))}</font>', ST["small_dark"]),
            Paragraph(esc(trigger_phrase(claim) or "Review retained wording"), ST["small_dark"]),
            Paragraph(esc(bounded_text(claim_source(claim), 55)), ST["small"]),
        ])
    if not claims:
        rows.append([Paragraph("—", ST["small"]), Paragraph("No material claim signal retained", ST["small"]), Paragraph("—", ST["small"]), Paragraph("—", ST["small"])])
    table = Table(rows, colWidths=[8 * mm, 57 * mm, 47 * mm, CONTENT_W - 112 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, GREY_300),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, row), (-1, row), GREY_100))
    table.setStyle(TableStyle(style))
    return table


def claim_card(claim: dict, material: bool = False) -> Table:
    risk = claim_risk(claim)
    accent = risk_color(risk)
    title_row = Table([[
        Paragraph(esc(claim_title(claim)), ST["claim_title"]),
        Paragraph(esc(risk), ParagraphStyle("rr", parent=ST["claim_risk"], textColor=accent)),
    ]], colWidths=[CONTENT_W * 0.78 - 20, CONTENT_W * 0.22])
    title_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    src = Paragraph(f'<font color="#7A8A93">Source:</font> {esc(claim_source(claim))}', ST["tiny"])
    excerpt = Paragraph(highlighted_excerpt(claim, 290 if material else 330), ST["quote"])
    why = Paragraph(f'<font color="#195A53"><b>WHY IT MATTERS</b></font><br/>{esc(why_text(claim))}', ST["small_dark"])
    gap = Paragraph(f'<font color="#A87311"><b>EVIDENCE GAP</b></font><br/>{esc(evidence_gap_text(claim))}', ST["small_dark"])
    wg = Table([[why, gap]], colWidths=[(CONTENT_W - 34) / 2] * 2)
    wg.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, GREY_300),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 7),
        ("LEFTPADDING", (1, 0), (1, 0), 7),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    recommendation = Paragraph(
        f'<font color="#2F7D55"><b>RECOMMENDED WORDING</b></font> {esc(rewrite_text(claim))}',
        ST["small_dark"],
    )
    inner = Table([[title_row], [src], [excerpt], [wg], [recommendation]], colWidths=[CONTENT_W - 22])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1),
    ]))
    card = Table([[inner]], colWidths=[CONTENT_W])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_SOFT if material else GREY_100),
        ("BOX", (0, 0), (-1, -1), 0.75, accent if material else GREY_300),
        ("LINEBEFORE", (0, 0), (0, 0), 3.5 if material else 2.5, TEAL if not material else accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 11 if material else 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11 if material else 8),
    ]))
    return card


def actions_table(data: dict) -> Table:
    name = company_name(data)
    raw = list(data.get("company_action_plan") or [])[:3]
    defaults = [
        {"title": "Review priority claims", "action": "Review the exact wording, audience, scope and supporting evidence for each retained claim."},
        {"title": "Close evidence gaps", "action": "Create or update claim-specific evidence files and assign an accountable owner."},
        {"title": "Implement claim governance", "action": "Require sustainability, legal, compliance and marketing review before publication."},
    ]
    while len(raw) < 3:
        raw.append(defaults[len(raw)])
    rows = []
    for idx, item in enumerate(raw, 1):
        title, description = compact_action(item, name)
        rows.append([
            Paragraph(str(idx), ParagraphStyle("an", parent=ST["claim_title"], alignment=TA_CENTER)),
            Paragraph(f'<b>{esc(title)}</b><br/>{esc(description)}', ST["small_dark"]),
        ])
    table = Table(rows, colWidths=[10 * mm, CONTENT_W - 10 * mm])
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, GREY_300),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), GREY_100),
        ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    table.setStyle(TableStyle(style))
    return table


def external_signal_card(signal: dict) -> Table:
    """Compact external-context card used in the dedicated page-2 section."""
    title = bounded_text(signal.get("title") or "External public-source signal", 105)
    status = bounded_text(signal.get("status") or "Review signal", 52)
    content = first_sentence(signal.get("content") or "", 205)
    url = clean_text(signal.get("url") or "")
    if url:
        parsed = urlparse(url)
        source_line = bounded_text((parsed.netloc + parsed.path).replace("www.", ""), 105)
    else:
        source_line = "Source link not available"

    rows = [
        [Paragraph(esc(title), ST["claim_title"])],
        [Paragraph(f'<font color="#AF3D43"><b>{esc(status)}</b></font>', ST["tiny"])],
    ]
    if content:
        rows.append([Paragraph(esc(content), ST["tiny"])])
    rows.append([Paragraph(f'<font color="#7A8A93">Source:</font> {esc(source_line)}', ST["tiny"])])

    inner = Table(rows, colWidths=[CONTENT_W * 0.49 - 16])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    card = Table([[inner]], colWidths=[CONTENT_W * 0.49])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RED_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("LINEBEFORE", (0, 0), (0, 0), 2.7, RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def external_signals_panel(data: dict) -> Table:
    """Dedicated external public-source section, separate from methodology."""
    signals = external_signals(data, 2)
    context_note = Paragraph(
        "Contextual public-source signals only. Their status, entity link and relevance to a specific claim require manual verification.",
        ST["tiny"],
    )
    if not signals:
        empty = Table([[Paragraph(
            "No relevant external public-source signal was retained in this scan, or external search coverage was insufficient.",
            ST["small"],
        )]], colWidths=[CONTENT_W])
        empty.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREY_100),
            ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        wrapper = Table([[context_note], [empty]], colWidths=[CONTENT_W])
    elif len(signals) == 1:
        wrapper = Table([[context_note], [external_signal_card(signals[0])]], colWidths=[CONTENT_W])
    else:
        cards = Table([[external_signal_card(signals[0]), external_signal_card(signals[1])]],
                      colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
        cards.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 3),
            ("LEFTPADDING", (1, 0), (1, 0), 3),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        wrapper = Table([[context_note], [cards]], colWidths=[CONTENT_W])
    wrapper.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return wrapper


def sources_methodology_panel(data: dict) -> Table:
    """Compact closing notes panel. External signals are intentionally excluded."""
    source_items = reviewed_sources(data, 3)
    source_html = "<br/>".join(f'• {esc(item)}' for item in source_items) if source_items else "No source list available."
    methodology = (
        "Risk bands: 0–44 Low · 45–74 Medium · 75–89 High · 90–100 Very high. "
        "EmpCo is applied to consumer-facing environmental and selected social claims. "
        "The Forced Labour Regulation lens is applied to forced-labour and supply-chain wording."
    )
    left = [
        Paragraph("<b>SOURCES REVIEWED</b>", ST["card_label"]),
        Paragraph(source_html, ST["tiny"]),
    ]
    right = [
        Paragraph("<b>METHODOLOGY REFERENCE</b>", ST["card_label"]),
        Paragraph(esc(methodology), ST["tiny"]),
        Spacer(1, 1.2 * mm),
        Paragraph("<b>Full methodology:</b> see the methodology PDF available from the scan homepage.", ST["tiny"]),
    ]
    panel = Table([[left, right]], colWidths=[CONTENT_W * 0.43, CONTENT_W * 0.57])
    panel.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("LINEBEFORE", (1, 0), (1, 0), 0.45, GREY_300),
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return panel



def assessment_basis_panel(data: dict) -> Table:
    meta = metadata(data)
    lens = (
        "EmpCo / Directive (EU) 2024/825 for consumer-facing environmental and selected social claims; "
        "EU Forced Labour Regulation for forced-labour and supply-chain wording."
    )
    coverage = [
        Paragraph("<b>COVERAGE</b>", ST["card_label"]),
        Paragraph(esc(meta["coverage"]), ST["small_dark"]),
        Paragraph(esc(bounded_text(meta["source"], 72)), ST["tiny"]),
    ]
    confidence = [
        Paragraph("<b>CONFIDENCE</b>", ST["card_label"]),
        Paragraph(esc(meta["confidence"]), ParagraphStyle("ab_conf", parent=ST["claim_title"], textColor=risk_color(meta["confidence"]))),
        Paragraph(esc(meta["confidence_reason"]), ST["tiny"]),
    ]
    regulatory = [
        Paragraph("<b>REGULATORY LENS</b>", ST["card_label"]),
        Paragraph(esc(lens), ST["tiny"]),
    ]
    panel = Table([[coverage, confidence, regulatory]], colWidths=[CONTENT_W * 0.27, CONTENT_W * 0.30, CONTENT_W * 0.43])
    panel.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, GREY_300),
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return panel

def draw_footer(canvas, doc):
    page = canvas.getPageNumber()
    name = company_name(getattr(doc, "report_data", {}) or {})
    canvas.saveState()
    canvas.setStrokeColor(GREY_300)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, 8.2 * mm, PAGE_W - MARGIN_X, 8.2 * mm)
    canvas.setFont("Helvetica-Oblique", 5.4)
    canvas.setFillColor(GREY_500)
    disclaimer = "Indicative screening only — not legal advice. Results require legal, compliance and subject-matter review before external use."
    canvas.drawString(MARGIN_X, 5.4 * mm, disclaimer)
    canvas.drawRightString(PAGE_W - MARGIN_X, 5.4 * mm, f"© Durably · {name} · Page {page} of 2")
    canvas.restoreState()


def build_company_report_pdf(data: dict) -> bytes:
    """Build the live two-page native PDF used by /api/report/pdf."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        allowSplitting=1,
    )
    doc.report_data = data

    claims = combined_top_claims(data, 3)
    material = claims[0] if claims else {
        "claim_type": "No material claim signal retained",
        "risk": "Low",
        "claim_text": "No material problematic sustainability claim was retained in the reviewed material.",
        "why_flagged": "No material wording issue was retained in this first-pass screening.",
        "evidence_needed": ["Continue maintaining claim-specific evidence and approval records"],
        "suggested_rewrite": "Continue using precise, claim-specific wording supported by current evidence.",
    }
    additional = claims[1:3]

    flow = []
    # Page 1
    flow += header_block(data, "Company claim-risk report · Assessment overview")
    flow.append(summary_box(data))
    flow.append(Spacer(1, 3.5 * mm))
    flow.append(section_title("Score overview"))
    flow.append(score_row(data))
    flow.append(Spacer(1, 3.5 * mm))
    flow.append(section_title("Top risk drivers"))
    flow.append(risk_driver_table(claims))
    flow.append(Spacer(1, 3.8 * mm))
    flow.append(section_title("Most material finding"))
    flow.append(KeepTogether(claim_card(material, material=True)))
    flow.append(Spacer(1, 3.2 * mm))
    flow.append(assessment_basis_panel(data))

    flow.append(PageBreak())

    # Page 2: internal findings -> external context -> actions -> reference notes
    flow += header_block(data, "Company claim-risk report · Findings, external context and actions")
    flow.append(section_title("Additional priority claims"))
    if additional:
        for claim in additional:
            flow.append(KeepTogether(claim_card(claim, material=False)))
            flow.append(Spacer(1, 2.2 * mm))
    else:
        flow.append(Table([[Paragraph("No additional material claim signal was retained beyond the finding shown on page 1.", ST["small"])]], colWidths=[CONTENT_W], style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, GREY_300),
            ("BACKGROUND", (0, 0), (-1, -1), GREY_100),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])))
    flow.append(Spacer(1, 1.8 * mm))
    flow.append(section_title("External public-source signals"))
    flow.append(external_signals_panel(data))
    flow.append(Spacer(1, 2.0 * mm))
    flow.append(section_title("Priority actions"))
    flow.append(actions_table(data))
    flow.append(Spacer(1, 2.2 * mm))
    flow.append(sources_methodology_panel(data))

    doc.build(flow, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


if __name__ == "__main__":
    import json
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "/tmp/scan_result.json"
    target = sys.argv[2] if len(sys.argv) > 2 else "/tmp/company_report_test.pdf"
    with open(source, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    with open(target, "wb") as handle:
        handle.write(build_company_report_pdf(payload))
    print(target)
