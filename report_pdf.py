"""Readable native Durably company claim-risk report (v87).

The live /api/report/pdf endpoint calls build_company_report_pdf(data). The report
uses a minimum body size of 9 pt and targets 2 pages, protecting that target by
reducing the amount of detail rather than shrinking fonts; content that still doesn't
fit spills to a 3rd page (see the pagination note further down) instead of being cut.
"""
from __future__ import annotations

import io
import re
from copy import deepcopy
from html import escape as _escape
from urllib.parse import urlparse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

PAGE_W, PAGE_H = A4
MARGIN_X = 13 * mm
MARGIN_TOP = 10 * mm
MARGIN_BOTTOM = 13 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

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
GREY_100 = colors.HexColor("#F7F9FA")
WHITE = colors.white


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=9.0, leading=11.3, textColor=GREY_700)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


# No report content is set below 7.5 pt. The footer is 6.5 pt.
ST = {
    "brand": _style("brand", fontName="Helvetica-Bold", fontSize=8.2, leading=9.6, textColor=TEAL_DARK),
    "title": _style("title", fontName="Helvetica-Bold", fontSize=20.0, leading=21.5, textColor=NAVY),
    "subtitle": _style("subtitle", fontSize=9.2, leading=11.0, textColor=GREY_700),
    "meta": _style("meta", fontSize=8.0, leading=9.5, textColor=GREY_700, alignment=TA_RIGHT),
    "meta_b": _style("meta_b", fontName="Helvetica-Bold", fontSize=7.5, leading=8.7, textColor=GREY_500, alignment=TA_RIGHT),
    "section": _style("section", fontName="Helvetica-Bold", fontSize=10.5, leading=12.0, textColor=NAVY, spaceBefore=3, spaceAfter=3),
    "body": _style("body", fontSize=9.0, leading=11.4, textColor=GREY_700),
    "body_dark": _style("body_dark", fontSize=9.0, leading=11.4, textColor=GREY_900),
    "small": _style("small", fontSize=8.5, leading=10.6, textColor=GREY_700),
    "small_dark": _style("small_dark", fontSize=8.5, leading=10.6, textColor=GREY_900),
    "source": _style("source", fontSize=7.7, leading=9.3, textColor=GREY_500),
    "quote": _style("quote", fontSize=8.5, leading=10.6, textColor=GREY_900, backColor=colors.HexColor("#FFFDF6")),
    "card_label": _style("card_label", fontName="Helvetica-Bold", fontSize=7.5, leading=8.8, textColor=TEAL_DARK),
    "card_num": _style("card_num", fontName="Helvetica-Bold", fontSize=18.0, leading=19.0, textColor=NAVY),
    "claim_title": _style("claim_title", fontName="Helvetica-Bold", fontSize=9.4, leading=11.2, textColor=NAVY),
    "claim_risk": _style("claim_risk", fontName="Helvetica-Bold", fontSize=8.5, leading=10.0, alignment=TA_RIGHT, wordWrap="LTR"),
    "claim_risk_badge": _style("claim_risk_badge", fontName="Helvetica-Bold", fontSize=8.2, leading=9.4, alignment=TA_CENTER, textColor=WHITE, wordWrap="LTR"),
    "table": _style("table", fontSize=8.0, leading=9.8, textColor=GREY_700),
    "table_dark": _style("table_dark", fontSize=8.0, leading=9.8, textColor=GREY_900),
    "table_head": _style("table_head", fontName="Helvetica-Bold", fontSize=8.0, leading=9.8, textColor=WHITE),
    "footer": _style("footer", fontName="Helvetica-Oblique", fontSize=6.5, leading=7.5, textColor=GREY_500),
}


def esc(value) -> str:
    return _escape(str(value if value is not None else ""), quote=False)


def clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


_DANGLING_TRAIL_WORDS = {
    # English
    "and", "or", "the", "a", "an", "of", "in", "on", "at", "to", "is", "are",
    "with", "by", "for", "as", "that", "this", "not", "no", "its", "it's",
    # Dutch -- the scanner quotes NL website/claim text directly into this report, so an
    # excerpt truncated right after "...duurzame producten en" or "...leveranciers van"
    # needs the same dangling-word guard as the English case.
    "en", "of", "de", "het", "een", "van", "in", "op", "aan", "met", "voor",
    "door", "niet", "geen", "is", "zijn", "dat", "deze", "dit",
    # French -- likewise for FR-quoted excerpts.
    "et", "ou", "le", "la", "les", "de", "du", "des", "dans", "à", "en",
    "pour", "par", "avec", "ce", "cette", "n'est", "pas", "que", "qui",
}


def bounded_text(value, max_chars: int, suffix: str = ".") -> str:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    # Reserve room for the suffix up front in every branch below, not just after the fact --
    # appending it to an already-full max_chars-length slice pushed the result past the
    # caller's budget by len(suffix), which matters for a fixed-width table column.
    budget = max(0, max_chars - len(suffix))
    cut = text[:budget].rsplit(" ", 1)[0].rstrip(" ,;:.")
    if not cut or len(cut) < budget * 0.6:
        # Either no space at all within the budget (e.g. a long URL/no-space token scraped
        # from an href/alt attribute), or the trailing word straddling the cutoff is so long
        # that dropping it whole would waste most of the budget -- e.g. "DOC - a-very-long-
        # filename-with-no-spaces.pdf" previously collapsed to just "DOC -." because the only
        # space in the whole string is right before that one long token. Hard-truncate the
        # token itself instead of discarding it outright.
        return text[:budget].rstrip() + suffix
    # Word-boundary truncation can still leave a dangling conjunction/article as the
    # final word (e.g. "...limitations and"), or end partway through an opened-but-
    # never-closed quotation (e.g. "...matching the “Absolute or purity environmental" --
    # the quote mark opened several words earlier, not just on the final word). Keep
    # backing up one word at a time rather than ship a fragment ending in "and." or a
    # dangling, unclosed quote.
    def _unclosed_quote(s):
        return (s.count("“") + s.count("”") + s.count('"')) % 2 == 1
    while cut:
        bare = cut.rsplit(" ", 1)[-1].strip("“”\"'").lower()
        if bare in _DANGLING_TRAIL_WORDS or _unclosed_quote(cut):
            cut = cut.rsplit(" ", 1)[0].rstrip(" ,;:.") if " " in cut else ""
        else:
            break
    if cut:
        return cut + suffix
    # Backing up word-by-word can exhaust the whole cut without ever reaching quote parity --
    # that happens when the unmatched mark sits early in the window, not near the cut point, so
    # trimming from the right never removes it. Falling back to a raw character slice of the
    # full value would reintroduce the exact fragment/dangling-word bug this function exists to
    # prevent, so instead strip quote characters outright from the in-budget prefix (a missing
    # quote mark is far less noticeable than a dangling unclosed one) and re-check for a
    # trailing dangling word once more.
    safe = text[:budget].rsplit(" ", 1)[0].rstrip(" ,;:.")
    safe = safe.replace("“", "").replace("”", "").replace('"', "").rstrip(" ,;:.")
    bare = safe.rsplit(" ", 1)[-1].strip("'").lower() if safe else ""
    if bare in _DANGLING_TRAIL_WORDS and " " in safe:
        safe = safe.rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (safe or text[:budget].rstrip()) + suffix


def first_sentence(value, max_chars=190) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    if parts and len(parts[0]) <= max_chars:
        return parts[0]
    return bounded_text(text, max_chars)


def risk_color(risk):
    text = str(risk or "").lower()
    if "high" in text:
        return RED
    if "medium" in text or "elev" in text or "mod" in text:
        return AMBER
    return GREEN


def risk_soft(risk):
    text = str(risk or "").lower()
    if "high" in text:
        return RED_SOFT
    if "medium" in text or "elev" in text or "mod" in text:
        return AMBER_SOFT
    return GREEN_SOFT


def risk_rank(claim):
    risk = str(claim.get("risk_level") or claim.get("risk") or "").lower()
    return 4 if "very" in risk else 3 if "high" in risk else 2 if ("medium" in risk or "elev" in risk) else 1


def is_material(claim):
    typ = str(claim.get("claim_type") or claim.get("type") or "").lower()
    return not (typ.startswith("no material") or typ.startswith("no major"))


def claim_title(claim):
    return clean_text(claim.get("claim_type") or claim.get("type") or "Sustainability claim")


def claim_risk(claim):
    return clean_text(claim.get("risk_level") or claim.get("risk") or "Review")


def legal_basis_label(claim):
    if str(claim.get("legal_basis_category") or "").lower() == "prohibited":
        return "Potentially Prohibited (Annex I)", RED
    return "Problematic (case-by-case)", AMBER


def claim_source(claim):
    source = clean_text(claim.get("source_label") or claim.get("source_url") or "Reviewed material")
    if source.startswith("http"):
        parsed = urlparse(source)
        filename = parsed.path.rsplit("/", 1)[-1]
        return filename or parsed.netloc.replace("www.", "")
    return source


def trigger_phrase(claim):
    phrase = clean_text(claim.get("matched_phrase") or "")
    if phrase:
        return phrase
    terms = claim.get("problematic_terms") or []
    return clean_text(terms[0]) if terms else ""


def claim_excerpt(claim, max_chars=220):
    text = clean_text(claim.get("claim_text") or claim.get("claim") or "")
    if len(text) <= max_chars:
        return text
    phrase = trigger_phrase(claim)
    if phrase:
        i = text.lower().find(phrase.lower())
        if i >= 0:
            start = max(0, i - 80)
            if start:
                next_space = text.find(" ", start)
                if 0 <= next_space < i:
                    start = next_space + 1
            end = min(len(text), i + len(phrase) + 110)
            snippet = text[start:end]
            if start:
                snippet = "Context: " + snippet
            return bounded_text(snippet, max_chars)
    return bounded_text(text, max_chars)


def highlighted_excerpt(claim, max_chars=220):
    text = esc(claim_excerpt(claim, max_chars))
    phrase = trigger_phrase(claim)
    if not phrase:
        return text
    try:
        return re.sub(re.escape(esc(phrase)), lambda m: f'<b backColor="#FFF1A8">{m.group(0)}</b>', text, flags=re.I)
    except re.error:
        return text


def why_text(claim, max_chars=150):
    raw = claim.get("why_flagged") or claim.get("risk_reason") or claim.get("issue") or claim.get("analysis")
    if raw:
        return bounded_text(raw, max_chars)
    phrase = trigger_phrase(claim)
    return bounded_text(f'The wording “{phrase}” requires claim-specific substantiation and audience review.', max_chars)


def evidence_gap_text(claim, max_chars=125):
    evidence = claim.get("evidence_needed")
    if isinstance(evidence, (list, tuple)) and evidence:
        # Truncate at whole-item boundaries rather than mid-item: a semicolon-joined list
        # cut by raw character count can land inside the last item (e.g. "limitations and
        # exclusions" -> "limitations and"), which bounded_text's dangling-word cleanup can
        # only patch up to a point. Keep only as many complete items as fit.
        items = [str(x) for x in evidence[:5]]
        kept, total = [], 0
        for item in items:
            added = (2 if kept else 0) + len(item)
            if kept and total + added > max_chars:
                break
            kept.append(item)
            total += added
        result = "; ".join(kept) if kept else "; ".join(items)
        return result + "." if len(result) <= max_chars else bounded_text(result, max_chars)
    if isinstance(evidence, str) and evidence:
        return bounded_text(evidence, max_chars)
    return "Scope, methodology, evidence period, verification basis and limitations."


def rewrite_text(claim, max_chars=180):
    raw = clean_text(claim.get("suggested_rewrite") or claim.get("rewrite") or "")
    if raw:
        return bounded_text(raw, max_chars)
    typ = claim_title(claim).lower()
    if "label" in typ or "certif" in typ:
        return bounded_text("Name the scheme owner, criteria, independent verifier, audited scope and validity period, or clarify that the wording is not independent certification.", max_chars)
    if "climate" in typ or "carbon" in typ or "offset" in typ:
        return bounded_text("Separate actual reductions from offsets and disclose boundary, baseline, method, residual emissions, offset use and reporting period.", max_chars)
    return bounded_text("Use precise wording and disclose scope, method, evidence, reporting period and limitations.", max_chars)


def ready_to_use_rewrite_text(claim, max_chars=220):
    raw = clean_text(claim.get("ready_to_use_rewrite") or "")
    return bounded_text(raw, max_chars) if raw else ""


def cluster_claims(data):
    rows = list(data.get("claim_inventory") or data.get("findings") or [])
    if not rows:
        rows = list(data.get("green_findings") or []) + list(data.get("social_findings") or [])
    clusters = {}
    for raw in rows:
        if not isinstance(raw, dict) or not is_material(raw):
            continue
        item = dict(raw)
        key = claim_title(item).lower()
        if key not in clusters:
            clusters[key] = {"representative": item, "occurrences": [item]}
        else:
            c = clusters[key]
            c["occurrences"].append(item)
            old = c["representative"]
            if (risk_rank(item), float(item.get("claim_score") or 0)) > (risk_rank(old), float(old.get("claim_score") or 0)):
                c["representative"] = item
    out = list(clusters.values())
    out.sort(key=lambda c: (risk_rank(c["representative"]), float(c["representative"].get("claim_score") or 0)), reverse=True)
    for c in out:
        c["representative"]["_occurrence_count"] = len(c["occurrences"])
        c["representative"]["_occurrence_sources"] = list(dict.fromkeys(claim_source(x) for x in c["occurrences"]))
    return out


def company_name(data):
    comp = data.get("company") or {}
    if isinstance(comp, dict):
        name = clean_text(comp.get("company") or comp.get("name"))
    else:
        name = clean_text(comp)
    return name if name and name.lower() != "company reviewed" else "Company"


def _is_internal_document_scan(data):
    return str(data.get("assessment_type") or "").lower() == "internal_document" or bool(data.get("document_type"))


def metadata(data):
    pages_list, documents_list, inv_summary = scan_inventory_items(data)
    is_internal_doc = _is_internal_document_scan(data)
    confidence = data.get("confidence") or {}
    context = data.get("entity_context_indicator") or {}
    assessment = "Internal document scan" if is_internal_doc else "Website scan"
    reasons = confidence.get("reasons") or []
    # app.py's build_confidence() returns each reason as a lowercase phrase fragment (e.g.
    # "external public-source search was active"), meant to be read as a standalone bullet, not
    # already-capitalized sentences -- joining them as-is with ". " produced grammatically broken
    # mid-paragraph lowercase sentence starts ("...reviewed. external public-source search was
    # active. claim-level signals were detected.") in the rendered PDF on every scan with more
    # than one reason. Capitalize each fragment's first letter before joining.
    def _cap(s):
        s = clean_text(s).rstrip(".")
        return s[:1].upper() + s[1:] if s else s
    reason_text = ". ".join(_cap(x) for x in reasons if clean_text(x))
    if reason_text:
        reason_text += "."
    if is_internal_doc:
        coverage = f"{len(documents_list)} document(s) reviewed" if documents_list else "Coverage not available"
    else:
        domains = int(inv_summary.get("domains_reviewed") or 0)
        total = len(pages_list) + len(documents_list)
        coverage = f"{total} page(s)/document(s) across {domains} domain(s)" if total else "Coverage not available"
    return {
        "source": clean_text(data.get("source_label") or data.get("original_url") or "Reviewed material"),
        "date": clean_text(data.get("analysis_date") or "")[:10],
        "assessment": assessment,
        "coverage": coverage,
        "confidence": clean_text(confidence.get("level") or "Not assessed"),
        "confidence_reason": bounded_text(reason_text or "Confidence reflects source access, coverage and external-search availability.", 210),
        "entity_level": clean_text(context.get("level") or "Not assessed"),
        "entity_note": bounded_text(context.get("note") or "Entity context is shown separately from claim risk.", 145),
    }


def reliability_warning(data):
    warning = clean_text(data.get("data_reliability_warning") or (data.get("confidence") or {}).get("reliability_warning"))
    if warning:
        return warning
    if _is_internal_document_scan(data):
        # No website crawl/fetch diagnostics apply to a standalone internal-document scan.
        return ""
    diag = data.get("crawl_diagnostics") or {}
    attempted = int(diag.get("pages_attempted") or 0)
    failed = int(diag.get("pages_failed") or 0)
    thin = int(diag.get("pages_thin") or 0)
    fallback = int(diag.get("pages_retrieved_via_fallback") or 0)
    pages_list, documents_list, _ = scan_inventory_items(data)
    pages = len(pages_list) + len(documents_list)
    caution = "A low risk score from this scan may reflect limited access to the site's content, not necessarily a genuine absence of risky claims."
    if attempted and failed / max(1, attempted) > .25:
        return f"{failed} of {attempted} page fetches failed. {caution}"
    if pages < 3:
        return f"Only {pages} relevant company page(s) could be reviewed. {caution}"
    if thin:
        return f"{thin} reviewed page(s) returned unusually little text. {caution}"
    if fallback:
        return f"{fallback} reviewed page(s) required a public text-extraction fallback. {caution}"
    return ""


def external_signals(data, limit=2):
    ext = data.get("external_research") or {}
    green_rows = (ext.get("green") or {}).get("targeted_negative_sources") or []
    social_rows = (ext.get("social") or {}).get("targeted_negative_sources") or []
    legacy_rows = ext.get("targeted_negative_sources") or []
    # v84: was green-then-social sequential, so once `limit` was reached from green sources
    # alone, social coverage could be entirely absent from the report even when real social
    # sources existed and were retained. Alternate the two, mirroring the same fairness fix
    # already applied to the live frontend's renderExternal().
    rows = []
    for i in range(max(len(green_rows), len(social_rows))):
        if i < len(green_rows): rows.append(green_rows[i])
        if i < len(social_rows): rows.append(social_rows[i])
    rows += legacy_rows
    unique, seen = [], set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("review_status") or "").lower().startswith("candidate"):
            continue
        # V69 safety gate: the report displays only signals that passed the backend's
        # explicit negative-polarity classifier. Positive or neutral articles are omitted.
        if str(item.get("polarity") or "").lower() != "negative":
            continue
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def reviewed_sources(data, limit=3):
    pages = list((data.get("report") or {}).get("pages_reviewed") or [])
    out = []
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
        label = bounded_text(label, 82)
        if label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out



def scan_inventory_items(data):
    inventory=data.get("scan_inventory") or {}
    pages=list(inventory.get("website_pages") or [])
    documents=list(inventory.get("documents") or [])
    if pages or documents:
        return pages, documents, inventory.get("summary") or {}
    # Backward-compatible fallback for older scan payloads.
    fallback=[]
    for value in (data.get("report") or {}).get("pages_reviewed") or []:
        url=clean_text(value)
        if not url: continue
        low=url.lower().split("?",1)[0]
        fallback.append({
            "name": claim_source({"source_label":url}),
            "url":url,
            "source_type":"Document / PDF" if low.endswith(".pdf") else "Website page",
            "document_type":"PDF document" if low.endswith(".pdf") else "Website page",
        })
    pages=[x for x in fallback if x.get("source_type")=="Website page"]
    documents=[x for x in fallback if x.get("source_type")!="Website page"]
    domains={urlparse(clean_text(x.get("url"))).netloc.replace("www.","") for x in fallback if urlparse(clean_text(x.get("url"))).netloc}
    return pages,documents,{"website_pages_reviewed":len(pages),"documents_reviewed":len(documents),"domains_reviewed":len(domains),"reviewed_total":len(fallback)}


def inventory_source_label(item, max_chars=72):
    url=clean_text(item.get("url") or "")
    name=clean_text(item.get("name") or "")
    prefix="DOC" if item.get("source_type")!="Website page" else "PAGE"
    if url.startswith("http"):
        parsed=urlparse(url)
        domain=parsed.netloc.replace("www.","")
        path=(parsed.path or "").strip("/")
        path_label=path.rsplit("/",1)[-1].replace("-"," ").replace("_"," ") if path else "homepage"
        label=f"{prefix} - {domain} - {path_label}"
    else:
        label=f"{prefix} - {name or url or 'reviewed source'}"
    status=clean_text(item.get("analysis_status") or "")
    if status:
        label=f"{label} - {status}"
    return bounded_text(label,max_chars)

def header_block(data, subtitle):
    meta = metadata(data)
    left = [Paragraph("DURABLY SUSTAINABILITY CLAIMS RISK SCAN", ST["brand"]), Spacer(1, 1 * mm), Paragraph(esc(company_name(data)), ST["title"]), Paragraph(esc(subtitle), ST["subtitle"])]
    right = [Paragraph("REVIEWED SOURCE", ST["meta_b"]), Paragraph(esc(bounded_text(meta["source"], 70)), ST["meta"]), Paragraph(f'{esc(meta["date"])} · {esc(meta["assessment"])}', ST["meta"]), Paragraph(esc(meta["coverage"]), ST["meta"]), Paragraph(f'Confidence: <b>{esc(meta["confidence"])}</b>', ST["meta"])]
    t = Table([[left, right]], colWidths=[CONTENT_W * .64, CONTENT_W * .36])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 1.2, NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [t, Spacer(1, 2 * mm)]


def section_title(text):
    return Paragraph(esc(text.upper()), ST["section"])


def summary_box(data, clusters):
    global_score = data.get("global_score", data.get("overall_score", "—"))
    global_risk = data.get("global_risk", data.get("overall_risk", "Not assessed"))
    types = [claim_title(c["representative"]) for c in clusters[:3]]
    summary = "The main retained claim areas are " + ", ".join(types) + "." if types else "No material claim signal was retained."
    left = Paragraph(f'<b>Overall result: {esc(global_score)}/100 — {esc(global_risk)} claim risk.</b> {esc(summary)}', ST["body_dark"])
    note = Paragraph(esc(bounded_text(data.get("fallback_note") or "Verify the reviewed entity and source scope before relying on the result.", 170)), ST["small"])
    t = Table([[left, note]], colWidths=[CONTENT_W * .73, CONTENT_W * .27])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("BACKGROUND", (0, 0), (0, 0), AMBER_SOFT), ("LINEBEFORE", (0, 0), (0, 0), 2.8, AMBER), ("BACKGROUND", (1, 0), (1, 0), GREY_100), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def score_card(label, value, risk, note="", card_width=None):
    risk_col = risk_color(risk)
    card_width = card_width or (CONTENT_W * .25 - 4)
    inner_width = card_width - 14
    rows = [[Paragraph(esc(label.upper()), ST["card_label"])], [Paragraph(f'{esc(value)}<font size="7.5" color="#7A8A93">/100</font>' if isinstance(value, (int, float)) else esc(value), ST["card_num"])], [Paragraph(f'<font color="{risk_col.hexval()}"><b>{esc(risk)}</b></font>', ST["small_dark"])]]
    if note:
        rows.append([Paragraph(esc(bounded_text(note, 115)), ST["source"])])
    inner = Table(rows, colWidths=[inner_width])
    inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    card = Table([[inner]], colWidths=[card_width])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("LINEBEFORE", (0, 0), (0, 0), 2.6, risk_col), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return card



def context_card(level, note, card_width=None):
    risk_col = risk_color(level)
    card_width = card_width or (CONTENT_W * .25 - 4)
    inner_width = card_width - 14
    rows = [
        [Paragraph("ENTITY CONTEXT", ST["card_label"])],
        [Paragraph(esc(level), ST["card_num"])],
        [Paragraph(esc(bounded_text(note, 115)), ST["source"])],
    ]
    inner = Table(rows, colWidths=[inner_width])
    inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    card = Table([[inner]], colWidths=[card_width])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("LINEBEFORE", (0, 0), (0, 0), 2.6, risk_col), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return card

def score_row(data):
    ctx = data.get("entity_context_indicator") or {}
    column_width = CONTENT_W * .25
    card_width = column_width - 4
    cards = [score_card("Overall claims risk", data.get("global_score", data.get("overall_score", "—")), data.get("global_risk", data.get("overall_risk", "Not assessed")), card_width=card_width), score_card("Green claims risk", data.get("green_score", "—"), data.get("green_risk", "Not assessed"), card_width=card_width), score_card("Social claims risk", data.get("social_score", "—"), data.get("social_risk", "Not assessed"), card_width=card_width), context_card(clean_text(ctx.get("level") or "Not assessed"), ctx.get("note") or "", card_width=card_width)]
    t = Table([cards], colWidths=[column_width] * 4)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def reliability_panel(data):
    warning = reliability_warning(data)
    if not warning:
        return None
    p = Paragraph(f'<b>DATA RELIABILITY</b><br/>{esc(warning)}', ST["small_dark"])
    t = Table([[p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBER_SOFT), ("BOX", (0, 0), (-1, -1), .7, AMBER), ("LINEBEFORE", (0, 0), (0, 0), 3, AMBER), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def risk_driver_table(clusters):
    headers = [Paragraph("#", ST["table_head"]), Paragraph("CLAIM AREA", ST["table_head"]), Paragraph("FLAGGED WORDING", ST["table_head"]), Paragraph("SOURCE", ST["table_head"])]
    rows = [headers]
    for idx, c in enumerate(clusters[:3], 1):
        claim = c["representative"]
        count = len(c["occurrences"])
        title = claim_title(claim) + (f" · {count} occurrences" if count > 1 else "")
        sources = "; ".join(list(dict.fromkeys(claim_source(x) for x in c["occurrences"]))[:2])
        rows.append([Paragraph(str(idx), ST["table"]), Paragraph(f'<b>{esc(bounded_text(title, 62))}</b><br/><font color="#7A8A93">{esc(claim_risk(claim))}</font>', ST["table_dark"]), Paragraph(esc(bounded_text(trigger_phrase(claim) or "Review retained wording", 42)), ST["table"]), Paragraph(esc(bounded_text(sources, 58)), ST["table"])])
    if len(rows) == 1:
        rows.append([Paragraph("—", ST["table"]), Paragraph("No material signal", ST["table"]), Paragraph("—", ST["table"]), Paragraph("Reviewed material", ST["table"])])
    t = Table(rows, colWidths=[9*mm, 67*mm, 47*mm, CONTENT_W-123*mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE), ("BOX", (0, 0), (-1, -1), .55, GREY_300), ("INNERGRID", (0, 0), (-1, -1), .4, GREY_300), ("BACKGROUND", (0, 1), (-1, -1), GREY_100), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def claim_card(cluster, excerpt_chars=220, material=False):
    claim = cluster["representative"]
    count = len(cluster["occurrences"])
    title = claim_title(claim) + (f" · {count} occurrences" if count > 1 else "")
    sources = "; ".join(list(dict.fromkeys(claim_source(x) for x in cluster["occurrences"]))[:2])
    # The risk level is deliberately rendered as a fixed-width badge on the LEFT
    # of the title. Earlier versions placed a right-aligned risk label at the outer
    # edge of a nested table. ReportLab can expand that nested table when a long
    # title has a large minimum width, allowing "High" / "Very high" to cross the
    # card border. The left badge removes that edge condition completely and keeps
    # every risk label inside the claim card in all renderers.
    outer_padding = 8  # points, must match the card TableStyle below
    safety_gutter = 2 * mm
    inner_width = CONTENT_W - (2 * outer_padding) - safety_gutter
    risk_width = 25 * mm
    title_width = inner_width - risk_width
    risk_value = claim_risk(claim)
    risk_badge = Paragraph(esc(risk_value), ST["claim_risk_badge"])
    lb_text, lb_color = legal_basis_label(claim)
    title_html = f'{esc(title)} <font size="7" color="{lb_color.hexval()}"><b>&nbsp;&nbsp;{esc(lb_text)}</b></font>'
    head = Table(
        [[risk_badge, Paragraph(title_html, ST["claim_title"])]],
        colWidths=[risk_width, title_width],
        hAlign="LEFT",
    )
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), risk_color(risk_value)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 4),
        ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ("TOPPADDING", (0, 0), (0, 0), 3),
        ("BOTTOMPADDING", (0, 0), (0, 0), 3),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (1, 0), (1, 0), 0),
        ("BOTTOMPADDING", (1, 0), (1, 0), 0),
    ]))
    source = Paragraph(f'<font color="#7A8A93">Source:</font> {esc(bounded_text(sources, 105))}', ST["source"])
    quote = Paragraph(highlighted_excerpt(claim, excerpt_chars), ST["quote"])
    why = Paragraph(f'<b>WHY IT MATTERS</b><br/>{esc(why_text(claim, 155 if material else 130))}', ST["small_dark"])
    gap = Paragraph(f'<b>EVIDENCE GAP</b><br/>{esc(evidence_gap_text(claim, 130 if material else 110))}', ST["small_dark"])
    grid = Table([[why, gap]], colWidths=[inner_width*.52, inner_width*.48])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBEFORE", (1, 0), (1, 0), .4, GREY_300), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 7), ("LEFTPADDING", (1, 0), (1, 0), 7), ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    rec = Paragraph(f'<b>RECOMMENDED IMPROVEMENT</b> {esc(rewrite_text(claim, 190 if material else 155))}', ST["small_dark"])
    rows = [[head], [source], [quote], [grid], [rec]]
    ready_rewrite = ready_to_use_rewrite_text(claim, 320 if material else 230)
    if ready_rewrite:
        rows.append([Paragraph(f'<b>READY-TO-USE REWRITE</b><br/><font face="Courier">{esc(ready_rewrite)}</font>', ST["small_dark"])])
    inner = Table(rows, colWidths=[inner_width])
    inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    card = Table([[inner]], colWidths=[CONTENT_W])
    # v86: the "most material finding" card always used GREEN_SOFT as its background
    # regardless of actual risk, while its border/badge correctly followed risk_color() -- a
    # High-risk finding rendered with a red badge, a red border, AND a soft-green card
    # background, which read as visually contradictory ("this looks like a good result").
    # risk_soft() picks the matching soft tone (red/amber/green) for the actual risk level.
    card_background = risk_soft(claim_risk(claim)) if material else GREY_100
    card.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), card_background), ("BOX", (0, 0), (-1, -1), .7, risk_color(claim_risk(claim))), ("LINEBEFORE", (0, 0), (0, 0), 3, risk_color(claim_risk(claim))), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return card


def compact_action(action, company):
    title = clean_text(action.get("title") or "Priority action")
    low = title.lower()
    if "green" in low or "empco" in low:
        return title, "Review exact consumer-facing wording and confirm scope, methodology, evidence, verification basis and limitations before reuse."
    if "social" in low:
        return title, "Document stakeholder scope, KPIs, workforce or audit evidence, grievance and remedy arrangements, and clear limitations."
    if "forced" in low or "supplier" in low:
        return title, "Document product and supplier traceability, risk assessment, mitigation, grievance, remediation and response readiness."
    if "evidence file" in low or "evidence" in low:
        return title, "Create one evidence file per claim with approved wording, source, owner, evidence link, review status and next review date."
    raw = clean_text(action.get("action") or action.get("description") or "")
    return title, bounded_text(raw, 155) if raw else "Assign an owner, evidence file, review status and completion date."


def actions_table(data):
    raw = list(data.get("company_action_plan") or [])[:3]
    defaults = [{"title":"Review priority claims","action":"Review exact wording, audience, scope and supporting evidence."},{"title":"Close evidence gaps","action":"Create claim-specific evidence files with accountable owners."},{"title":"Implement claim governance","action":"Require sustainability, legal, compliance and marketing approval before publication."}]
    while len(raw) < 3:
        raw.append(defaults[len(raw)])
    rows = []
    for idx, item in enumerate(raw, 1):
        title, desc = compact_action(item, company_name(data))
        rows.append([Paragraph(str(idx), ParagraphStyle(f"act{idx}", parent=ST["claim_title"], alignment=TA_CENTER)), Paragraph(f'<b>{esc(title)}</b><br/>{esc(desc)}', ST["small_dark"])])
    t = Table(rows, colWidths=[10*mm, CONTENT_W-10*mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("INNERGRID", (0, 0), (-1, -1), .4, GREY_300), ("BACKGROUND", (0, 0), (-1, -1), GREY_100), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def external_signal_card(signal, width):
    title = bounded_text(signal.get("title") or "External public-source signal", 90)
    status = bounded_text(signal.get("status") or "Status unclear", 38)
    review = bounded_text(signal.get("review_status") or "Retained — manual verification required", 50)
    source = signal.get("source_name") or urlparse(clean_text(signal.get("url"))).netloc.replace("www.", "") or clean_text(signal.get("category") or "External source")
    date = clean_text(signal.get("published_date") or "Date not available")
    content = first_sentence(signal.get("content") or "", 160)
    related = clean_text(signal.get("related_claim_area") or ("Environmental claims" if signal.get("dimension") == "green" else "Social / labour claims"))
    rows = [[Paragraph(esc(title), ST["claim_title"])], [Paragraph(f'<b>{esc(source)}</b> · {esc(date)}<br/><font color="#AF3D43">{esc(status)}</font> · {esc(review)}', ST["source"])]]
    if content:
        rows.append([Paragraph(esc(content), ST["small"])])
    rows.append([Paragraph(f'<b>Related claim area:</b> {esc(related)} · <b>Entity match:</b> {esc(signal.get("entity_match") or "Direct")}', ST["source"])])
    inner = Table(rows, colWidths=[width-16])
    inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    card = Table([[inner]], colWidths=[width])
    card.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RED_SOFT), ("BOX", (0, 0), (-1, -1), .6, GREY_300), ("LINEBEFORE", (0, 0), (0, 0), 2.8, RED), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return card


def external_panel(data, limit):
    signals = external_signals(data, limit)
    note = Paragraph("Negative external stakeholder signals only. Positive, neutral and company-owned sources are excluded. Automated retained signals require manual verification of status, entity link and claim relevance.", ST["source"])
    if not signals:
        empty_text = ("External-source screening was not performed for this internal-document scan."
                      if _is_internal_document_scan(data) else
                      "No negative external public-source signal was retained. If external search was unavailable, this does not confirm an absence of relevant criticism or enforcement.")
        cards = Table([[Paragraph(empty_text, ST["small"])]], colWidths=[CONTENT_W])
        cards.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("BACKGROUND", (0, 0), (-1, -1), GREY_100), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    elif len(signals) == 1:
        cards = external_signal_card(signals[0], CONTENT_W)
    else:
        half_width = CONTENT_W * .5
        # Each outer cell adds a 3 pt gutter, so the card itself must be narrower
        # than the nominal half-page column.
        cards = Table([[external_signal_card(signals[0], half_width-3), external_signal_card(signals[1], half_width-3)]], colWidths=[half_width, half_width])
        cards.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 3), ("LEFTPADDING", (1, 0), (1, 0), 3), ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    wrap = Table([[note], [cards]], colWidths=[CONTENT_W])
    wrap.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 3), ("BOTTOMPADDING", (0, 1), (-1, 1), 0)]))
    return wrap


def assessment_basis(data):
    meta = metadata(data)
    left = [Paragraph("<b>COVERAGE AND CONFIDENCE</b>", ST["card_label"]), Paragraph(f'{esc(meta["coverage"])} · {esc(meta["confidence"])}', ST["small_dark"]), Paragraph(esc(meta["confidence_reason"]), ST["source"])]
    right = [Paragraph("<b>REGULATORY LENS</b>", ST["card_label"]), Paragraph("EmpCo for consumer-facing environmental and selected social claims; Forced Labour Regulation as the forced-labour and supply-chain assurance lens.", ST["source"])]
    t = Table([[left, right]], colWidths=[CONTENT_W*.52, CONTENT_W*.48])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_300), ("LINEBEFORE", (1, 0), (1, 0), .4, GREY_300), ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _int_or(summary, key, default):
    value = summary.get(key)
    return int(value) if value is not None else default


def coverage_sources_methodology(data, limit=5):
    pages,documents,summary=scan_inventory_items(data)
    combined=pages+documents
    shown=combined[:max(1,limit)]
    total=len(combined)
    count_line=(f'{_int_or(summary,"website_pages_reviewed",len(pages))} website page(s) · '
                f'{_int_or(summary,"documents_reviewed",len(documents))} document(s) / PDF(s) · '
                f'{_int_or(summary,"domains_reviewed",0)} domain(s)')
    source_lines=[inventory_source_label(x) for x in shown]
    if total>len(shown):
        source_lines.append(f'+ {total-len(shown)} additional reviewed source(s) listed in the online scan')
    left=[Paragraph("<b>REVIEWED PAGES AND DOCUMENTS</b>",ST["card_label"]),
          Paragraph(esc(count_line),ST["small_dark"]),
          Paragraph("<br/>".join(f'• {esc(x)}' for x in source_lines) if source_lines else "Source list not available.",ST["source"])]
    right=[Paragraph("<b>METHODOLOGY</b>",ST["card_label"]),
           Paragraph("The online source register distinguishes fully analysed, partially analysed, limited-text and failed sources. Only text that entered the analysis can support findings. EmpCo, Forced Labour Regulation and Durably claim-risk methodology apply. See the detailed methodology PDF on the scan homepage.",ST["source"])]
    t=Table([[left,right]],colWidths=[CONTENT_W*.58,CONTENT_W*.42])
    t.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.6,GREY_300),("LINEBEFORE",(1,0),(1,0),.4,GREY_300),("BACKGROUND",(0,0),(-1,-1),BLUE_SOFT),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    return t


def _fit_text_to_width(text, font, size, max_width):
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    while text and stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1].rstrip()
    return (text + ellipsis) if text else ellipsis


def draw_footer(canvas, doc):
    page = canvas.getPageNumber()
    canvas.saveState()
    canvas.setStrokeColor(GREY_300)
    canvas.setLineWidth(.5)
    canvas.line(MARGIN_X, 8.5*mm, PAGE_W-MARGIN_X, 8.5*mm)
    font, size = "Helvetica-Oblique", 6.5
    canvas.setFont(font, size)
    canvas.setFillColor(GREY_500)
    disclaimer = "Indicative screening only — not legal advice. Results require legal, compliance and subject-matter review before external use."
    total = getattr(doc, 'total_pages_hint', None)
    page_label = f"Page {page} of {total}" if total else f"Page {page}"
    right_text = f"© Durably · {company_name(getattr(doc, 'report_data', {}) or {})} · {page_label}"
    # The disclaimer (left, drawString) and the company/page label (right, drawRightString)
    # were both drawn at the same y-coordinate with no width check against each other --
    # for a long company/legal name the two visually collided. Reserve a fixed gap and cap
    # the variable-length right side to at most 45% of the footer width so a long name never
    # eats into the disclaimer's space, then fit the disclaimer to whatever remains.
    available_w = PAGE_W - 2*MARGIN_X
    gap = 6*mm
    right_text = _fit_text_to_width(right_text, font, size, available_w*0.45)
    right_w = stringWidth(right_text, font, size)
    disclaimer = _fit_text_to_width(disclaimer, font, size, available_w - right_w - gap)
    canvas.drawString(MARGIN_X, 5.4*mm, disclaimer)
    canvas.drawRightString(PAGE_W-MARGIN_X, 5.4*mm, right_text)
    canvas.restoreState()


def _build_once(data, additional_limit=2, external_limit=2, excerpt_chars=220, source_limit=5, total_pages=None):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM, allowSplitting=1)
    doc.report_data = data
    doc.total_pages_hint = total_pages
    clusters = cluster_claims(data)
    material = clusters[0] if clusters else {"representative":{"claim_type":"No material claim signal retained","risk":"Low","claim_text":"No material sustainability claim was retained in the reviewed material.","why_flagged":"No material wording issue was retained in this first-pass screening.","evidence_needed":["Maintain claim-specific evidence and approval records"],"suggested_rewrite":"Continue using precise wording supported by current evidence."},"occurrences":[]}
    additional = clusters[1:1+additional_limit]
    # v85: clusters are sorted purely by (risk, claim_score) with no dimension awareness, so a
    # scan with e.g. three High-risk social findings but a slightly higher-scoring green
    # finding on top could show three green cards and zero social ones in the PDF, even though
    # social was the more material risk. If the finding shown as "most material" leaves the
    # OTHER dimension completely unrepresented, swap the lowest-ranked additional slot for the
    # best-ranked cluster of that missing dimension (only when there's room to do so).
    if additional:
        shown_dims = {str((material.get("representative") or {}).get("dimension","")).lower()}
        shown_dims |= {str(c.get("representative",{}).get("dimension","")).lower() for c in additional}
        other_dim = "social" if "green" in shown_dims and "social" not in shown_dims else ("green" if "social" in shown_dims and "green" not in shown_dims else "")
        if other_dim:
            shown_ids = {id(material)} | {id(c) for c in additional}
            candidate = next((c for c in clusters if str(c.get("representative",{}).get("dimension","")).lower()==other_dim and id(c) not in shown_ids), None)
            if candidate:
                additional[-1] = candidate
    flow = []
    flow += header_block(data, "Company claim-risk report · Assessment overview")
    flow.append(summary_box(data, clusters)); flow.append(Spacer(1, 2.5*mm))
    flow.append(section_title("Score overview")); flow.append(score_row(data)); flow.append(Spacer(1, 2.5*mm))
    rp = reliability_panel(data)
    if rp is not None:
        flow.append(rp); flow.append(Spacer(1, 2.2*mm))
    flow.append(section_title("Top risk drivers")); flow.append(risk_driver_table(clusters)); flow.append(Spacer(1, 2.8*mm))
    flow.append(section_title("Most material finding")); flow.append(KeepTogether(claim_card(material, excerpt_chars, True))); flow.append(Spacer(1, 2.5*mm))
    flow.append(assessment_basis(data)); flow.append(PageBreak())
    flow += header_block(data, "Company claim-risk report · Context and response")
    flow.append(section_title("Additional material findings"))
    if additional:
        for c in additional:
            flow.append(KeepTogether(claim_card(c, min(190, excerpt_chars), False))); flow.append(Spacer(1, 1.7*mm))
    else:
        flow.append(Paragraph("No additional material claim group is shown in this concise report. Full details remain available in the online scan.", ST["small"]))
    flow.append(Spacer(1, 1.4*mm)); flow.append(section_title("External public-source signals")); flow.append(external_panel(data, external_limit)); flow.append(Spacer(1, 1.8*mm))
    flow.append(section_title("Priority actions")); flow.append(actions_table(data)); flow.append(Spacer(1, 1.6*mm))
    flow.append(section_title("Assessment coverage")); flow.append(coverage_sources_methodology(data, source_limit))
    doc.build(flow, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


def _page_count(pdf_bytes):
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return None


def build_company_report_pdf(data: dict) -> bytes:
    """Build a two- or three-page PDF without reducing font sizes.

    Three pages is now an accepted outcome (the ready-to-use rewrite text needs the room), not
    just a two-page target. If content would still spill past three pages, the generator
    progressively limits the number of additional findings/external signals and shortens
    excerpts. Detailed content remains available in the online scan. Once a variant fits, the
    PDF is rebuilt once more with the known final page count so the footer can read "Page X of
    N" correctly instead of the two-page assumption baked into earlier drafts.
    """
    # v84: external_limit's top tier was 2 -- combined across BOTH green and social, so
    # up to 8 genuinely retained, filtered negative sources (now that targeted_negative_sources
    # allows up to 10 per dimension) could exist and still show at most 2 in the PDF. Raised the
    # starting tiers; the existing auto-shrink ladder below already handles the case where a
    # scan has too many findings/sources to fit 3 pages, same as it always has for
    # additional_limit/source_limit.
    variants = [
        dict(additional_limit=2, external_limit=6, excerpt_chars=220, source_limit=6),
        dict(additional_limit=2, external_limit=4, excerpt_chars=200, source_limit=5),
        dict(additional_limit=1, external_limit=3, excerpt_chars=180, source_limit=4),
        dict(additional_limit=1, external_limit=2, excerpt_chars=165, source_limit=3),
        dict(additional_limit=0, external_limit=1, excerpt_chars=150, source_limit=3),
    ]
    last = b""
    for variant in variants:
        probe = _build_once(deepcopy(data), **variant)
        count = _page_count(probe)
        if count is None:
            return probe
        if count <= 3:
            return _build_once(deepcopy(data), total_pages=count, **variant)
        last = probe
    return last


if __name__ == "__main__":
    import json, sys
    source = sys.argv[1] if len(sys.argv) > 1 else "/tmp/scan_result.json"
    target = sys.argv[2] if len(sys.argv) > 2 else "/tmp/company_report_test.pdf"
    with open(source, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    with open(target, "wb") as handle:
        handle.write(build_company_report_pdf(payload))
    print(target)
