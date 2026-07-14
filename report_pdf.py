"""Two-page company claim-risk report, generated as a native PDF with ReportLab.
Visual language matches methodology.pdf: Helvetica family, navy/teal brand palette,
numbered section headers, thin rule under the title block, light-grey table headers.
"""
import io
import re
from html import escape as _esc
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                 HRFlowable, PageBreak, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

NAVY = colors.HexColor('#173f5f')
INK = colors.HexColor('#132033')
MUTED = colors.HexColor('#5e6b7d')
LINE = colors.HexColor('#dfe5ee')
SOFT = colors.HexColor('#f6f8fb')
ACCENT = colors.HexColor('#265f5c')
GREEN = colors.HexColor('#276749')
GREEN_SOFT = colors.HexColor('#edf7f0')
AMBER = colors.HexColor('#9b6a17')
AMBER_SOFT = colors.HexColor('#fff8ea')
DANGER = colors.HexColor('#a43c3c')
DANGER_SOFT = colors.HexColor('#fff1f1')
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm

def _style(name, **kw):
    base = dict(fontName='Helvetica', fontSize=8.3, leading=11, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)

STY = {
    'kicker': _style('kicker', fontName='Helvetica-Bold', fontSize=8, textColor=ACCENT, leading=10),
    'title': _style('title', fontName='Helvetica-Bold', fontSize=17, textColor=NAVY, leading=20),
    'sub': _style('sub', fontName='Helvetica', fontSize=8.5, textColor=MUTED, leading=11),
    'meta': _style('meta', fontName='Helvetica', fontSize=8, textColor=MUTED, leading=11, alignment=TA_RIGHT),
    'meta_b': _style('meta_b', fontName='Helvetica-Bold', fontSize=8, textColor=INK, alignment=TA_RIGHT),
    'h2': _style('h2', fontName='Helvetica-Bold', fontSize=11.5, textColor=NAVY, leading=14, spaceBefore=9, spaceAfter=4),
    'h3': _style('h3', fontName='Helvetica-Bold', fontSize=8.7, textColor=NAVY, leading=11),
    'body': _style('body', fontSize=8.6, leading=12),
    'small': _style('small', fontSize=7.8, leading=10.5, textColor=MUTED),
    'small_b': _style('small_b', fontName='Helvetica-Bold', fontSize=7.8, leading=10.5, textColor=MUTED),
    'quote': _style('quote', fontSize=8.6, leading=11.5, textColor=INK, backColor=colors.HexColor('#fffdf4')),
    'foot': _style('foot', fontName='Helvetica-Oblique', fontSize=7.6, leading=10, textColor=MUTED),
    'score_num': _style('score_num', fontName='Helvetica-Bold', fontSize=22, leading=24, textColor=NAVY),
    'score_lbl': _style('score_lbl', fontName='Helvetica-Bold', fontSize=7.3, leading=9, textColor=MUTED),
    'score_risk': _style('score_risk', fontName='Helvetica-Bold', fontSize=9.5, leading=12),
}


def esc(s):
    return _esc(str(s if s is not None else ''), quote=False)


def risk_color(risk):
    r = (risk or '').lower()
    if 'very' in r or 'high' in r:
        return DANGER
    if 'elev' in r or 'medium' in r or 'mod' in r:
        return AMBER
    return GREEN


def risk_soft(risk):
    r = (risk or '').lower()
    if 'very' in r or 'high' in r:
        return DANGER_SOFT
    if 'elev' in r or 'medium' in r or 'mod' in r:
        return AMBER_SOFT
    return GREEN_SOFT


def level_band(score):
    """Mirrors the backend's level() thresholds exactly, so the printed legend
    can never disagree with the score shown next to it."""
    if score is None:
        return '—'
    if score >= 90:
        return 'Very high'
    if score >= 75:
        return 'High'
    if score >= 45:
        return 'Medium'
    return 'Low'


def highlight(text, terms):
    """Bold the trigger phrase(s) inside a claim passage. Mirrors the frontend's
    highlightTerms(), longest term first so partial overlaps don't break tags."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    safe = esc(text)
    terms = [str(t).strip() for t in (terms or []) if t and len(str(t).strip()) > 1]
    terms = sorted(set(terms), key=len, reverse=True)[:12]
    for t in terms:
        pat = re.escape(esc(t))
        try:
            safe = re.sub('(' + pat + ')', r'<b backColor="#fff1a8">\1</b>', safe, flags=re.IGNORECASE)
        except re.error:
            pass
    return safe or '<i>No exact passage available.</i>'


def is_material(claim):
    t = str(claim.get('claim_type') or claim.get('type') or '').lower()
    return not (t.startswith('no material') or t.startswith('no major'))


def top_claims(data, dim, n=3):
    rows = [c for c in (data.get('claim_inventory') or []) if str(c.get('dimension', '')).lower() == dim.lower()]
    if not rows:
        rows = data.get('green_findings' if dim.lower() == 'green' else 'social_findings') or []
    rows = [c for c in rows if is_material(c)]
    return _merge_duplicate_claims(rows)[:n]


def _merge_duplicate_claims(rows):
    """When several claim-type patterns match the exact same retained sentence, merge them into
    one card with a combined type label instead of showing the identical quote multiple times."""
    merged = []
    seen_text = {}
    for c in rows:
        key = re.sub(r'\s+', ' ', str(c.get('claim_text') or c.get('claim') or '')).strip().lower()[:200]
        if key and key in seen_text:
            existing = seen_text[key]
            t = c.get('claim_type') or c.get('type') or ''
            if t and t not in existing['claim_type']:
                existing['claim_type'] = existing['claim_type'] + ' + ' + t
            for term in (c.get('problematic_terms') or []):
                if term not in existing.setdefault('problematic_terms', []):
                    existing['problematic_terms'].append(term)
            continue
        c = dict(c)
        seen_text[key] = c
        merged.append(c)
    return merged


def header_block(data, page_title, page_sub, company_name=''):
    kicker = Paragraph('DURABLY SUSTAINABILITY SCAN &mdash; COMPANY CLAIM-RISK REPORT', STY['kicker'])
    cn = (company_name or '').strip()
    if cn and cn.lower() not in ('company reviewed', ''):
        title = Paragraph(esc(cn), STY['title'])
        sub = Paragraph(esc(page_title) + (' &mdash; ' + esc(page_sub) if page_sub else ''), STY['sub'])
    else:
        title = Paragraph(esc(page_title), STY['title'])
        sub = Paragraph(esc(page_sub), STY['sub'])
    left = [kicker, title, sub]

    src = (data.get('source_label') or data.get('original_url') or '')[:70]
    date = (data.get('analysis_date') or '')[:10]
    right = [Paragraph('Reviewed source', STY['meta_b']),
             Paragraph(esc(src) + ('…' if len(data.get('source_label') or '') > 70 else ''), STY['meta']),
             Paragraph(esc(date), STY['meta'])]

    left_flow = left
    tbl = Table([[left_flow, right]], colWidths=[(PAGE_W - 2 * MARGIN) * 0.66, (PAGE_W - 2 * MARGIN) * 0.34])
    tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    rule = HRFlowable(width='100%', thickness=1.4, color=NAVY, spaceBefore=4, spaceAfter=6)
    return [tbl, rule]


def score_box(label, num, risk, width=None):
    if width is None:
        width = (PAGE_W - 2 * MARGIN - 18) / 4
    color = risk_color(risk)
    inner = Table([
        [Paragraph(label.upper(), STY['score_lbl'])],
        [Paragraph(f'{num if num is not None else "—"}<font size=8 color="#8b9baa">/100</font>', STY['score_num'])],
        [Paragraph(esc(risk or '—'), ParagraphStyle('r', parent=STY['score_risk'], textColor=color))],
    ], colWidths=[width])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6), ('BOTTOMPADDING', (0, -1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, 1), 1), ('BOTTOMPADDING', (0, 1), (-1, 1), 1),
        ('LINEBEFORE', (0, 0), (0, -1), 3, color),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fbfcfe')),
    ]))
    return inner


def scores_row(data):
    gs, grs = data.get('global_score', data.get('overall_score')), data.get('global_risk', data.get('overall_risk'))
    gns, gnrs = data.get('green_score'), data.get('green_risk')
    ss, srs = data.get('social_score'), data.get('social_risk')
    box_w = (PAGE_W - 2 * MARGIN - 8) / 3
    boxes = [score_box('Global claims risk', gs, grs, box_w),
             score_box('Green claims risk', gns, gnrs, box_w),
             score_box('Social claims risk', ss, srs, box_w)]
    row = Table([boxes], colWidths=[(PAGE_W - 2 * MARGIN) / 3] * 3)
    row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                              ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return row


def _clean_flag_label(flag):
    """Reduce a verbose backend red-flag sentence to a short, plain-language label for the
    'at a glance' list, stripping the trailing regulatory-explanation clause and jargon so it
    reads as a quick concern tag rather than a repeat of the detailed claim card below."""
    f = re.sub(r'\s+', ' ', str(flag or '')).strip()
    f = re.sub(r'^(Potential |High-priority )?EmpCo blacklisted-practice indicator (where|if)\s*', '', f, flags=re.IGNORECASE)
    if f and f[0].islower():
        f = f[0].upper() + f[1:]
    f = f.split(' detected.')[0].split(' detected,')[0]
    f = re.sub(r'\s*Problematic trigger\(s\).*$', '', f, flags=re.IGNORECASE)
    f = re.sub(r'\s*Source:.*$', '', f, flags=re.IGNORECASE)
    f = f.rstrip('. ').strip()
    if len(f) > 92:
        f = f[:89].rsplit(' ', 1)[0] + '…'
    return f


def concerns_list(title, items, accent):
    labels = []
    for i in items or []:
        raw = str(i or '')
        if ' detected' not in raw:
            continue
        lbl = _clean_flag_label(raw)
        if lbl and lbl not in labels:
            labels.append(lbl)
    labels = labels[:5]
    body = '<br/>'.join('&bull;&nbsp; ' + esc(l) for l in labels) if labels else '<i>No specific concern retained in this category.</i>'
    body_style = ParagraphStyle('bb', parent=STY['small'], spaceAfter=0, leading=10.8)
    cell = Table([[Paragraph(esc(title), ParagraphStyle('t', parent=STY['h3'], textColor=accent))],
                  [Paragraph(body, body_style)]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 8) / 2])
    cell.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 7), ('BOTTOMPADDING', (0, -1), (-1, -1), 7),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), risk_soft('high') if accent == DANGER else GREEN_SOFT if accent == GREEN else AMBER_SOFT),
    ]))
    return cell


def claim_card(c, show_source=True):
    typ = c.get('claim_type') or c.get('type') or 'Claim signal'
    risk = c.get('risk_level') or c.get('risk') or ''
    src = (c.get('source_label') or c.get('source_url') or 'Reviewed material')[:80]
    text = c.get('claim_text') or c.get('claim') or ''
    text = re.sub(r'\s+', ' ', str(text)).strip()
    matched_phrase = str(c.get('matched_phrase') or '').strip()
    if len(text) > 125:
        # v57g: truncating from the start always lost the actual trigger wording whenever it sat
        # past character ~122 of a longer sentence -- the reader would see text that never shows
        # why the passage was flagged at all. Centre the shown window on the matched phrase
        # instead, so the trigger is always visible (and gets highlighted below).
        idx = text.lower().find(matched_phrase.lower()) if matched_phrase else -1
        if idx >= 0:
            start = max(0, idx - 45)
            end = min(len(text), idx + len(matched_phrase) + 55)
            snippet = text[start:end]
            if start > 0: snippet = '…' + snippet.lstrip()
            if end < len(text): snippet = snippet.rstrip() + '…'
            text = snippet
        else:
            text = text[:122].rsplit(' ', 1)[0] + '…'
    terms = c.get('problematic_terms') or []
    if matched_phrase and matched_phrase not in terms:
        terms = [matched_phrase] + list(terms)
    spec_status = (c.get('specification_check') or {}).get('status')
    head = Table([[Paragraph(esc(typ), STY['small_b']),
                   Paragraph(esc(risk), ParagraphStyle('rp', parent=STY['small_b'], textColor=risk_color(risk), alignment=TA_RIGHT))]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 40) * 0.7, (PAGE_W - 2 * MARGIN - 40) * 0.3])
    head.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    rows = [head]
    if show_source:
        rows.append(Paragraph(f'<font color="#8b9baa">Source:</font> {esc(src)}', STY['small']))
    quote_p = Paragraph(highlight(text, terms), STY['quote'])
    rows.append(quote_p)
    trig = ' &middot; '.join(f'<b backColor="#fff1a8">{esc(t)}</b>' for t in terms[:5]) or 'Pattern-based signal'
    trig_line = f'<font color="#6b4e00"><b>Trigger:</b></font> {trig}'
    if spec_status:
        trig_line += f'  <font color="#8b9baa">&middot; Substantiation in passage: <b>{esc(spec_status)}</b></font>'
    rows.append(Paragraph(trig_line, STY['small']))
    accent = GREEN if str(c.get('dimension', '')).lower() == 'green' else AMBER
    inner = Table([[r] for r in rows], colWidths=[PAGE_W - 2 * MARGIN - 20])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    wrap = Table([[inner]], colWidths=[PAGE_W - 2 * MARGIN])
    wrap.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE), ('LINEBEFORE', (0, 0), (0, 0), 2.5, accent),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafbfd')),
    ]))
    return KeepTogether(wrap)


def claim_section(title, rows, show_source=True):
    flow = [Paragraph(esc(title), STY['h3']), Spacer(1, 3)]
    if not rows:
        flow.append(Paragraph('<i>No material problematic claim signal retained.</i>', STY['small']))
        return flow
    for r in rows:
        flow.append(claim_card(r, show_source=show_source))
        flow.append(Spacer(1, 1.5))
    return flow


def driver_narrative(driver_data, fallback_comp=None):
    """Builds a readable 'why this score' block from score_driver_details (summary + key_drivers
    with real detected claim types) instead of a bare table of four unexplained numbers."""
    driver_data = driver_data or {}
    flow = []
    summary = driver_data.get('summary')
    if summary:
        flow.append(Paragraph(esc(summary), STY['small']))
        flow.append(Spacer(1, 3))
    key_drivers = driver_data.get('key_drivers') or []
    if key_drivers:
        items = '<br/>'.join('&bull;&nbsp; ' + esc(k) for k in key_drivers[:5])
        flow.append(Paragraph(items, ParagraphStyle('kd', parent=STY['small'], leading=10.8)))
    elif fallback_comp:
        comp = fallback_comp
        rows = [('Claim wording severity', '42%', comp.get('claim_wording_risk', '—')),
                ('Evidence / substantiation gap', '24%', comp.get('substantiation_risk', '—')),
                ('External stakeholder context', '22%', comp.get('external_context_risk', '—')),
                ('Sector & channel sensitivity', '12%', comp.get('sector_baseline_risk', '—'))]
        items = '<br/>'.join(f'&bull;&nbsp; {esc(r[0])} ({r[1]}): <b>{esc(r[2])}</b>/100' for r in rows)
        flow.append(Paragraph(items, ParagraphStyle('kd2', parent=STY['small'], leading=10.8)))
    return flow


def section_card(title, content, width=None):
    if width is None:
        width = PAGE_W - 2 * MARGIN
    body = [Paragraph(esc(title), STY['h3']), Spacer(1, 3)] + (content if isinstance(content, list) else [content])
    tbl = Table([[body]], colWidths=[width])
    tbl.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE), ('BACKGROUND', (0, 0), (-1, -1), WHITE),
    ]))
    return tbl


def footer(canvas, doc, right_text):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    y = MARGIN - 8
    canvas.line(MARGIN, y + 10, PAGE_W - MARGIN, y + 10)
    canvas.setFont('Helvetica-Oblique', 7.4)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, y, 'Indicative screening only — not legal advice. Results require legal, compliance and subject-matter review before external use.')
    canvas.setFont('Helvetica', 7.4)
    canvas.drawRightString(PAGE_W - MARGIN, y, right_text)
    canvas.restoreState()


def entity_context_and_confidence_row(data):
    """v57r: Entity context and Confidence shown as their own boxes, separate from the Global/
    Green/Social claim-risk scores above -- an entity-level signal (sector exposure, a retained
    controversy) is background, not evidence that a specific claim is misleading, and confidence
    tells the reader how much weight the scores above can bear."""
    eci = data.get('entity_context_indicator') or {}
    conf = data.get('confidence') or {}
    eci_level = eci.get('level', '—')
    conf_level = conf.get('level', '—')
    eci_color = {'Low': GREEN, 'Elevated': AMBER, 'High': DANGER, 'Very high': colors.HexColor('#7a1e1e')}.get(eci_level, MUTED)
    conf_color = {'High': GREEN, 'Medium': AMBER, 'Low': DANGER, 'Insufficient coverage': colors.HexColor('#7a1e1e')}.get(conf_level, MUTED)
    eci_box = Table([
        [Paragraph('ENTITY CONTEXT', STY['score_lbl'])],
        [Paragraph(esc(eci_level), ParagraphStyle('ec', parent=STY['score_num'], fontSize=15, textColor=eci_color))],
        [Paragraph(esc((eci.get('note') or 'Not assessed.')[:150]), STY['small'])],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 8) / 2])
    conf_box = Table([
        [Paragraph('CONFIDENCE', STY['score_lbl'])],
        [Paragraph(esc(conf_level), ParagraphStyle('cf', parent=STY['score_num'], fontSize=15, textColor=conf_color))],
        [Paragraph(esc((conf.get('reliability_warning') or '; '.join(conf.get('reasons') or []) or 'Standard scan coverage.')[:150]), STY['small'])],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 8) / 2])
    for box, c in ((eci_box, eci_color), (conf_box, conf_color)):
        box.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6), ('BOTTOMPADDING', (0, -1), (-1, -1), 6),
            ('TOPPADDING', (0, 1), (-1, 1), 1), ('BOTTOMPADDING', (0, 1), (-1, 1), 1),
            ('LINEBEFORE', (0, 0), (0, -1), 3, c), ('BOX', (0, 0), (-1, -1), 0.6, LINE),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fbfcfe')),
        ]))
    row = Table([[eci_box, conf_box]], colWidths=[(PAGE_W - 2 * MARGIN) / 2] * 2)
    row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                              ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return row


def combined_top_claims(data, n=3):
    """v57r: rank ALL retained claims (green + social together) by claim_score and return the
    top n -- the two-pager should surface the company's single most material issues, not a fixed
    3-green-plus-3-social split regardless of relative severity."""
    rows = [c for c in (data.get('claim_inventory') or []) if is_material(c)]
    rows = _merge_duplicate_claims(rows)
    rows.sort(key=lambda c: c.get('claim_score', 0), reverse=True)
    return rows[:n]


def top_risk_drivers_flow(data, n=3):
    """v57r: a short, scannable 'top N risk drivers' list for the assessment-overview page,
    distinct from (and above) the detailed priority-claim cards on page 2."""
    claims = combined_top_claims(data, n)
    if not claims:
        return [Paragraph('<i>No material risk driver was identified in this scan.</i>', STY['small'])]
    items = []
    for c in claims:
        typ = esc(c.get('claim_type') or c.get('type') or 'Claim signal')
        risk = c.get('risk_level') or c.get('risk') or ''
        src = esc((c.get('source_label') or c.get('source_url') or 'reviewed material')[:60])
        items.append(f'&bull;&nbsp; <b>{typ}</b> <font color="#8b9baa">({esc(risk)} &middot; {src})</font>')
    return [Paragraph('<br/>'.join(items), ParagraphStyle('trd', parent=STY['small'], leading=12))]


def priority_claim_card(c):
    """v57r: the five-field structure recommended for the two-pager's priority claims -- exact
    claim, source, why it matters, evidence gap, and recommended wording -- shown explicitly
    rather than folded into a single 'why retained' note, so a reader can act on each field."""
    typ = c.get('claim_type') or c.get('type') or 'Claim signal'
    risk = c.get('risk_level') or c.get('risk') or ''
    src = (c.get('source_label') or c.get('source_url') or 'Reviewed material')[:80]
    text = c.get('claim_text') or c.get('claim') or ''
    text = re.sub(r'\s+', ' ', str(text)).strip()
    matched_phrase = str(c.get('matched_phrase') or '').strip()
    if len(text) > 160:
        idx = text.lower().find(matched_phrase.lower()) if matched_phrase else -1
        if idx >= 0:
            start = max(0, idx - 55); end = min(len(text), idx + len(matched_phrase) + 70)
            snippet = text[start:end]
            if start > 0: snippet = '…' + snippet.lstrip()
            if end < len(text): snippet = snippet.rstrip() + '…'
            text = snippet
        else:
            text = text[:157].rsplit(' ', 1)[0] + '…'
    terms = c.get('problematic_terms') or []
    if matched_phrase and matched_phrase not in terms:
        terms = [matched_phrase] + list(terms)

    why = str(c.get('why_flagged') or c.get('risk_reason') or c.get('issue') or '').strip()
    why = re.sub(r'\s+', ' ', why)
    if len(why) > 190: why = why[:187].rsplit(' ', 1)[0] + '…'

    evidence = c.get('evidence_needed')
    if isinstance(evidence, (list, tuple)) and evidence:
        gap = '; '.join(str(x) for x in evidence[:2])
    elif isinstance(evidence, str) and evidence:
        gap = evidence
    else:
        gap = 'Scope, methodology, evidence date and limitations should be disclosed alongside this claim.'
    if len(gap) > 190: gap = gap[:187].rsplit(' ', 1)[0] + '…'

    rewrite = str(c.get('suggested_rewrite') or c.get('rewrite') or '').strip()
    rewrite = re.sub(r'\s+', ' ', rewrite)
    if len(rewrite) > 190: rewrite = rewrite[:187].rsplit(' ', 1)[0] + '…'

    head = Table([[Paragraph(esc(typ), STY['small_b']),
                   Paragraph(esc(risk), ParagraphStyle('rp2', parent=STY['small_b'], textColor=risk_color(risk), alignment=TA_RIGHT))]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 40) * 0.7, (PAGE_W - 2 * MARGIN - 40) * 0.3])
    head.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    rows = [head, Paragraph(f'<font color="#8b9baa">Source:</font> {esc(src)}', STY['small'])]
    rows.append(Paragraph(highlight(text, terms), STY['quote']))
    if why:
        rows.append(Paragraph(f'<font color="#174e78"><b>Why it matters:</b></font> {esc(why)}', STY['small']))
    rows.append(Paragraph(f'<font color="#6b4e00"><b>Evidence gap:</b></font> {esc(gap)}', STY['small']))
    if rewrite:
        rows.append(Paragraph(f'<font color="#276749"><b>Recommended wording:</b></font> {esc(rewrite)}', STY['small']))
    accent = GREEN if str(c.get('dimension', '')).lower() == 'green' else AMBER
    inner = Table([[r] for r in rows], colWidths=[PAGE_W - 2 * MARGIN - 20])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    wrap = Table([[inner]], colWidths=[PAGE_W - 2 * MARGIN])
    wrap.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE), ('LINEBEFORE', (0, 0), (0, 0), 2.5, accent),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafbfd')),
    ]))
    return KeepTogether(wrap)


def build_company_report_pdf(data):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                             topMargin=MARGIN, bottomMargin=MARGIN + 6)

    company_name = ((data.get('company') or {}).get('company') or '').strip()
    priority_claims = combined_top_claims(data, 3)
    sources = {(c.get('source_label') or c.get('source_url') or '') for c in priority_claims}
    shared_source = len(sources) == 1 and priority_claims
    actions = (data.get('company_action_plan') or [])[:3]
    ext = ((data.get('external_research', {}).get('green', {}).get('targeted_negative_sources') or []) +
           (data.get('external_research', {}).get('social', {}).get('targeted_negative_sources') or []) +
           (data.get('external_research', {}).get('targeted_negative_sources') or []))[:2]
    who = company_name if company_name and company_name.lower() != 'company reviewed' else 'This company'

    # ---------- PAGE 1: Assessment overview ----------
    page1 = []
    page1 += header_block(data, 'Assessment overview',
                           'EmpCo (Directive (EU) 2024/825) · EU Forced Labour Regulation (EU) 2024/3015',
                           company_name)
    page1.append(scores_row(data))
    page1.append(Spacer(1, 4))
    page1.append(entity_context_and_confidence_row(data))
    page1.append(Spacer(1, 7))

    overall_risk = data.get('global_risk', data.get('overall_risk', ''))
    narrative = (f'<b>{esc(who)}</b> scores <b>{esc(str(data.get("global_score", data.get("overall_score", "—"))))}/100</b> '
                 f'overall (<b>{esc(overall_risk)}</b> claim-risk) on this scan, covering EmpCo green/social claim wording '
                 f'and EU Forced Labour Regulation supply-chain wording. See the risk drivers and entity-context note below '
                 f'for what mainly drove this result.')
    summary_flow = [Paragraph(narrative, STY['body'])]
    if data.get('data_reliability_warning'):
        cd = data.get('crawl_diagnostics') or {}
        detail = f' ({cd.get("pages_failed", 0)}/{cd.get("pages_attempted", 0)} page fetches failed.)' if cd.get('pages_attempted') else ''
        summary_flow.append(Spacer(1, 4))
        summary_flow.append(Paragraph(f'<b>&#9888; Data reliability warning:</b> {esc(data.get("data_reliability_warning"))}{esc(detail)}',
                                       ParagraphStyle('rw', parent=STY['small'], textColor=AMBER)))
    if data.get('fallback_note'):
        summary_flow.append(Spacer(1, 4))
        summary_flow.append(Paragraph(f'<b>Note:</b> {esc(data.get("fallback_note"))}',
                                       ParagraphStyle('rn', parent=STY['small'], textColor=AMBER)))
    page1.append(section_card('Executive conclusion', summary_flow))
    page1.append(Spacer(1, 5))
    page1.append(section_card('Top risk drivers', top_risk_drivers_flow(data, 3)))

    # ---------- PAGE 2: Findings and actions ----------
    page2 = []
    page2 += header_block(data, 'Findings and actions',
                           'Priority claims, external signals and recommended next steps', company_name)

    page2.append(Paragraph(esc(f'Priority claims (top {len(priority_claims)} by materiality)' if priority_claims else 'Priority claims'), STY['h3']))
    page2.append(Spacer(1, 3))
    if shared_source:
        src_label = (priority_claims[0].get('source_label') or priority_claims[0].get('source_url') or '')[:90]
        page2.append(Paragraph(f'<font color="#8b9baa">All claims below are from:</font> {esc(src_label)}', STY['small']))
        page2.append(Spacer(1, 3))
    if priority_claims:
        for c in priority_claims:
            page2.append(priority_claim_card(c))
            page2.append(Spacer(1, 2))
    else:
        page2.append(Paragraph('<i>No material problematic claim signal was retained in this scan.</i>', STY['small']))
    page2.append(Spacer(1, 4))

    if ext:
        ext_flow = []
        for x in ext:
            title_line = f'<b>{esc(x.get("title") or "External signal")}</b>'
            if x.get('status'): title_line += f'  <font color="#8b9baa">&middot; {esc(x.get("status"))}</font>'
            ext_flow.append(Paragraph(title_line, STY['small_b']))
            if x.get('url'):
                ext_flow.append(Paragraph(f'<font color="#174e78">{esc(x.get("url", "")[:100])}</font>', STY['small']))
            ext_flow.append(Paragraph(esc((x.get('content') or '')[:180]), STY['small']))
            if x.get('related_articles_count', 1) > 1:
                ext_flow.append(Paragraph(f'<font color="#8b9baa">+{x.get("related_articles_count")-1} related article(s) on the same topic.</font>', STY['small']))
            ext_flow.append(Spacer(1, 4))
    else:
        ext_flow = [Paragraph(f'<i>No external public-source signal retained for {esc(who)}, or external search not configured for this scan (see Confidence, page 1).</i>', STY['small'])]
    page2.append(section_card('External signals (verified, max 2 shown)', ext_flow))
    page2.append(Spacer(1, 4))

    if actions:
        act_flow = []
        for i, a in enumerate(actions, 1):
            act_flow.append(Paragraph(f'<b>{i}. {esc(a.get("title") or "")}</b>', STY['small_b']))
            txt = re.sub(r'\s+', ' ', str(a.get('action') or '')).strip()
            if len(txt) > 175:
                txt = txt[:172].rsplit(' ', 1)[0] + '…'
            act_flow.append(Paragraph(esc(txt), STY['small']))
            act_flow.append(Spacer(1, 2))
    else:
        act_flow = [Paragraph('<b>1. Review retained claim signals</b>', STY['small_b']),
                    Paragraph('Attach evidence, scope and approval records to each claim before reuse.', STY['small'])]
    page2.append(section_card(f'Priority actions for {who}' if who != 'This company' else 'Priority actions', act_flow))
    page2.append(Spacer(1, 4))

    # v57r: reviewer feedback -- the two-pager is a management decision document, not the
    # methodology document. The exact score formula, weights and gating rules now live only in
    # the standalone methodology PDF; this page just points there.
    method_note = Paragraph(
        'Risk bands: 0&ndash;44 Low &middot; 45&ndash;74 Medium &middot; 75&ndash;89 High &middot; 90&ndash;100 Very high. '
        'Lenses: EmpCo &mdash; Directive (EU) 2024/825 &mdash; for green and (secondarily, Art. 6(1)(b)) social claims, applicable '
        'from 27 September 2026; EU Forced Labour Regulation (EU) 2024/3015) for forced-labour/supply-chain claims, core '
        'provisions applicable from 14 December 2027. Full scoring formula, weights, gating rules and claim taxonomy: '
        'see the methodology PDF.', STY['small'])
    page2.append(section_card('Methodology snapshot', method_note))

    flowables = page1 + [PageBreak()] + page2

    def on_page1(c, d):
        footer(c, d, f'© Durably · {who if who != "This company" else "Company"} · Page 1 of 2')

    def on_page2(c, d):
        footer(c, d, f'© Durably · {who if who != "This company" else "Company"} · Page 2 of 2')

    doc.build(flowables, onFirstPage=on_page1, onLaterPages=on_page2)
    return buf.getvalue()


if __name__ == '__main__':
    import json
    data = json.load(open('/tmp/scan_result.json'))
    pdf_bytes = build_company_report_pdf(data)
    open('/tmp/company_report_test.pdf', 'wb').write(pdf_bytes)
    print('Generated', len(pdf_bytes), 'bytes')
