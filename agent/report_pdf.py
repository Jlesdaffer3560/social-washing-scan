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
from reportlab.graphics.shapes import Drawing, Rect, Line, String

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


def smart_truncate(text, max_len):
    """v57u: naive character-slicing (text[:150]) cuts mid-word with no indication that anything
    was cut -- a real report showed 'migrant or seasonal l' where 'labour' was chopped in half.
    Trim at the last full word before the limit and add an ellipsis so truncation is visible."""
    text = str(text or '')
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(' ', 1)[0]
    return (cut or text[:max_len]).rstrip('.,;: ') + '…'


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

    src = (data.get('source_label') or data.get('original_url') or '')[:60]
    date = (data.get('analysis_date') or '')[:10]
    assessment_type = 'Internal document scan' if data.get('document_type') or 'document' in str(data.get('assessment_type', '')).lower() else 'Website scan'
    pages = data.get('report', {}).get('pages_reviewed') or []
    domains = {re.sub(r'^https?://(www\.)?', '', p).split('/')[0] for p in pages if p}
    coverage_line = f'{len(pages)} page(s) across {len(domains)} domain(s)' if pages else 'Coverage not available'
    confidence_level = (data.get('confidence') or {}).get('level', '—')
    right = [Paragraph('Reviewed source', STY['meta_b']),
             Paragraph(esc(src) + ('…' if len(data.get('source_label') or '') > 60 else ''), STY['meta']),
             Paragraph(esc(date) + '  \u00b7  ' + esc(assessment_type), STY['meta']),
             Paragraph(esc(coverage_line), STY['meta']),
             Paragraph('Confidence: ' + esc(confidence_level), ParagraphStyle('cf_h', parent=STY['meta_b'], textColor=NAVY))]

    left_flow = left
    tbl = Table([[left_flow, right]], colWidths=[(PAGE_W - 2 * MARGIN) * 0.62, (PAGE_W - 2 * MARGIN) * 0.38])
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


def risk_gauge(label, score, risk, width=None, height=36):
    """v57y: a genuine visual element (a coloured risk-band bar with a marker) rather than only
    numbers in boxes -- board-style reports typically pair a headline metric with a simple visual
    read of where it sits on the scale. Also, deliberately, this fills page real estate with
    purposeful content instead of leaving a large blank gap under a short text-only page 1."""
    if width is None:
        width = PAGE_W - 2 * MARGIN
    if score is None:
        score = 0
    score = max(0, min(100, score))
    d = Drawing(width, height)
    bar_y = 11
    bar_h = 11
    bands = [(0, 45, GREEN), (45, 75, AMBER), (75, 90, DANGER), (90, 100, colors.HexColor('#7a1e1e'))]
    for lo, hi, c in bands:
        x = width * (lo / 100.0)
        w = width * ((hi - lo) / 100.0)
        d.add(Rect(x, bar_y, w, bar_h, fillColor=c, strokeColor=colors.white, strokeWidth=1))
    marker_x = width * (score / 100.0)
    marker_x = max(1.5, min(width - 1.5, marker_x))
    d.add(Line(marker_x, bar_y - 4, marker_x, bar_y + bar_h + 4, strokeColor=INK, strokeWidth=2))
    d.add(String(min(width - 4, max(14, marker_x)), bar_y + bar_h + 6, f'{label}: {score}/100 ({risk or "\u2014"})',
                 fontName='Helvetica-Bold', fontSize=8.6, fillColor=INK, textAnchor='middle'))
    for lo, hi, c, name in [(0, 45, GREEN, 'Low'), (45, 75, AMBER, 'Medium'), (75, 90, DANGER, 'High'), (90, 100, colors.HexColor('#7a1e1e'), 'Very high')]:
        mid = width * ((lo + hi) / 2 / 100.0)
        d.add(String(mid, bar_y - 7, name, fontName='Helvetica', fontSize=6.6, fillColor=MUTED, textAnchor='middle'))
    return d


def dual_mini_gauge(green_score, green_risk, social_score, social_risk, width=None):
    """v57y: a compact side-by-side Green vs Social visual comparison -- two short horizontal
    bars sharing the same 0-100 scale, so the relative balance between the two dimensions is
    visible at a glance rather than only readable from two separate numbers."""
    if width is None:
        width = PAGE_W - 2 * MARGIN
    half = (width - 16) / 2
    height = 26
    rows = []
    for label, score, risk, accent in [('GREEN', green_score, green_risk, GREEN), ('SOCIAL', social_score, social_risk, AMBER)]:
        d = Drawing(half, height)
        track_y = 9
        track_h = 8
        d.add(Rect(0, track_y, half, track_h, fillColor=SOFT, strokeColor=LINE, strokeWidth=0.5))
        sc = max(0, min(100, score or 0))
        fill_w = half * (sc / 100.0)
        fill_color = risk_color(risk)
        if fill_w > 0:
            d.add(Rect(0, track_y, fill_w, track_h, fillColor=fill_color, strokeColor=None))
        d.add(String(0, track_y + track_h + 4, f'{label}  {sc}/100  ({esc(risk or "\u2014")})',
                     fontName='Helvetica-Bold', fontSize=7.6, fillColor=INK))
        rows.append(d)
    row = Table([rows], colWidths=[half, half])
    row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (0, 0), (0, 0), 16),
                              ('LEFTPADDING', (1, 0), (1, 0), 0), ('RIGHTPADDING', (1, 0), (1, 0), 0),
                              ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return row


def executive_conclusion_block(data, who):
    """v57t: given the top billing this text receives in the reviewer's own template ('Executive
    conclusion' is the first thing on the page, ahead of the score grid), it should read like a
    headline -- larger type, a colour accent tied to the overall risk level, generous whitespace
    -- rather than another small-print box that looks identical to every other card on the page."""
    overall_risk = data.get('global_risk', data.get('overall_risk', ''))
    overall_score = data.get('global_score', data.get('overall_score', '\u2014'))
    color = risk_color(overall_risk)
    r = (overall_risk or '').lower()
    color_hex = '#a43c3c' if ('very' in r or 'high' in r) else ('#9b6a17' if ('elev' in r or 'medium' in r or 'mod' in r) else '#276749')
    narrative = (f'{esc(who)} scores <b>{esc(str(overall_score))}/100</b> overall '
                 f'(<font color="{color_hex}"><b>{esc(overall_risk)}</b></font> claim-risk) on this scan, '
                 f'covering EmpCo green/social claim wording and EU Forced Labour Regulation supply-chain wording. '
                 f'See the risk drivers below and the entity-context note in the score summary for what mainly drove this result.')
    body = [Paragraph(narrative, ParagraphStyle('exec', parent=STY['body'], fontSize=9.4, leading=13, textColor=INK))]
    if data.get('data_reliability_warning'):
        cd = data.get('crawl_diagnostics') or {}
        detail = f' ({cd.get("pages_failed", 0)}/{cd.get("pages_attempted", 0)} page fetches failed.)' if cd.get('pages_attempted') else ''
        body.append(Spacer(1, 5))
        body.append(Paragraph(f'<b>&#9888; Data reliability:</b> {esc(data.get("data_reliability_warning"))}{esc(detail)}',
                               ParagraphStyle('rw2', parent=STY['small'], textColor=AMBER, fontSize=8.2)))
    if data.get('fallback_note'):
        body.append(Spacer(1, 3))
        body.append(Paragraph(f'<b>Note:</b> {esc(data.get("fallback_note"))}',
                               ParagraphStyle('rn2', parent=STY['small'], textColor=AMBER, fontSize=8.2)))
    inner = Table([[body]], colWidths=[PAGE_W - 2 * MARGIN - 16])
    inner.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    wrap = Table([[inner]], colWidths=[PAGE_W - 2 * MARGIN])
    wrap.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LINEBEFORE', (0, 0), (0, 0), 3.5, color), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fbfcfe')),
    ]))
    return wrap


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
    eci_note = smart_truncate(eci.get('note') or 'Not assessed.', 210)
    conf_reasons = conf.get('reasons') or []
    conf_text = conf.get('reliability_warning') or (', '.join(conf_reasons) + '.' if conf_reasons else 'Standard scan coverage.')
    conf_note = smart_truncate(conf_text, 210)
    eci_box = Table([
        [Paragraph('ENTITY CONTEXT', STY['score_lbl'])],
        [Paragraph(esc(eci_level), ParagraphStyle('ec', parent=STY['score_num'], fontSize=15, textColor=eci_color))],
        [Paragraph(esc(eci_note), ParagraphStyle('ecn', parent=STY['small'], leading=9.6))],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 8) / 2])
    conf_box = Table([
        [Paragraph('CONFIDENCE', STY['score_lbl'])],
        [Paragraph(esc(conf_level), ParagraphStyle('cf', parent=STY['score_num'], fontSize=15, textColor=conf_color))],
        [Paragraph(esc(conf_note), ParagraphStyle('cfn', parent=STY['small'], leading=9.6))],
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
    """v57r/v57u: rank ALL retained claims (green + social together) by claim_score and return
    the top n -- the two-pager should surface the company's most material *distinct* issues, not
    a fixed 3-green-plus-3-social split, and not multiple instances of the same claim type (a
    real report showed "Climate-neutrality or offsetting claim" twice in the top-3, which reads
    as repetitive rather than showing the breadth of concerns). Keep only the highest-scoring
    instance per claim type before ranking."""
    rows = [c for c in (data.get('claim_inventory') or []) if is_material(c)]
    rows = _merge_duplicate_claims(rows)
    rows.sort(key=lambda c: c.get('claim_score', 0), reverse=True)
    seen_types = set()
    distinct = []
    for c in rows:
        t = c.get('claim_type') or c.get('type') or ''
        if t in seen_types:
            continue
        seen_types.add(t)
        distinct.append(c)
    return distinct[:n]


def top_risk_drivers_flow(data, n=3):
    """v57r/v57t/v57z: a short, scannable 'top N risk drivers' list for the assessment-overview
    page, distinct from (and above) the detailed priority-claim cards on page 2. Each driver now
    also carries a one-line trigger snippet, so the list gives real differentiating information
    (what specifically was flagged) rather than only a type label repeated three times with
    different sources -- genuine content, not layout padding."""
    claims = combined_top_claims(data, n)
    if not claims:
        return [Paragraph('<i>No material risk driver was identified in this scan.</i>', STY['small'])]
    items = []
    for i, c in enumerate(claims, 1):
        typ = esc(c.get('claim_type') or c.get('type') or 'Claim signal')
        risk = c.get('risk_level') or c.get('risk') or ''
        src = esc((c.get('source_label') or c.get('source_url') or 'reviewed material')[:55])
        rl = risk.lower()
        num_color = '#a43c3c' if ('very' in rl or 'high' in rl) else ('#9b6a17' if ('elev' in rl or 'medium' in rl or 'mod' in rl) else '#276749')
        mp = str(c.get('matched_phrase') or '').strip()
        trigger_line = f'flagged wording: "{esc(mp)}"' if mp else ''
        second_line = f'<br/><font size=7.6 color="#5e6b7d">&nbsp;&nbsp;&nbsp;{trigger_line}</font>' if trigger_line else ''
        items.append(f'<font color="{num_color}"><b>{i}.</b></font>&nbsp; <b>{typ}</b> '
                      f'<font size=7.4 color="#8b9baa">({esc(risk)} &middot; {src})</font>'
                      f'{second_line}')
    joined = '<br/>'.join(items)
    return [Paragraph(joined, ParagraphStyle('trd', parent=STY['body'], fontSize=8.6, leading=13.5))]


def select_display_excerpt(text, matched_phrase, max_len=320):
    """v57x: replace character-window math entirely with sentence-based selection. Every
    previous version of this logic (a 160-char window, then a 90-char lookback, then a 260-char
    lookback) was still fundamentally "find a boundary within N characters of the match" -- which
    keeps failing for some real sentence, just a longer one each time, because the underlying
    approach is inherently fragile. Instead: split into sentences first (a guaranteed clean unit,
    already used by the backend's own excerpt logic), find the sentence containing the matched
    phrase, and show that complete sentence (plus the previous one for context if it is short).
    Character-window math is only used as a last resort *inside* one already-clean sentence, for
    the rare case where a single sentence alone exceeds max_len -- never spanning a sentence
    boundary, so a mid-sentence cut can no longer happen at the top-level selection."""
    text = (text or '').strip()
    if len(text) <= max_len:
        return text
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    mp = (matched_phrase or '').lower()
    if mp:
        for i, s in enumerate(sentences):
            if mp in s.lower():
                out = s
                if len(out) < 90 and i > 0:
                    out = sentences[i - 1] + ' ' + out
                if len(out) <= max_len:
                    return out
                # A single sentence longer than max_len: window strictly within this one
                # sentence, so the result still starts and ends inside a clean sentence unit.
                idx = out.lower().find(mp)
                start = max(0, idx - 90); end = min(len(out), idx + len(mp) + 110)
                snippet = out[start:end]
                if start > 0: snippet = '…' + snippet.lstrip()
                if end < len(out): snippet = snippet.rstrip() + '…'
                return snippet
    return smart_truncate(text, max_len)


def most_material_finding_spotlight(c):
    """v57z: page 1 previously closed with only meta-summary (score numbers, a bullet list of
    driver *labels*, a two-item action teaser) -- board readers reasonably read that as "thin"
    content even once the empty space below it was patched with a filler strip. This gives page 1
    genuine substance: the single most material finding, shown with its exact quote, source and
    recommended wording -- the actual headline fact of the report -- not just a pointer to detail
    that lives entirely on page 2. Deliberately shorter than priority_claim_card (no Why-it-
    matters/Evidence-gap split): this is the "if you read nothing else" spotlight, not a
    replacement for the full card repeated in detail on page 2."""
    if not c:
        return Paragraph('<i>No material finding was retained in this scan.</i>', STY['small'])
    typ = c.get('claim_type') or c.get('type') or 'Claim signal'
    risk = c.get('risk_level') or c.get('risk') or ''
    src = (c.get('source_label') or c.get('source_url') or 'Reviewed material')[:90]
    text = c.get('claim_text') or c.get('claim') or ''
    text = re.sub(r'\s+', ' ', str(text)).strip()
    matched_phrase = str(c.get('matched_phrase') or '').strip()
    text = select_display_excerpt(text, matched_phrase, 280)
    terms = c.get('problematic_terms') or []
    if matched_phrase and matched_phrase not in terms:
        terms = [matched_phrase] + list(terms)
    why = str(c.get('why_flagged') or c.get('risk_reason') or c.get('issue') or '').strip()
    if len(why) > 170: why = why[:167].rsplit(' ', 1)[0] + '…'
    rewrite = str(c.get('suggested_rewrite') or c.get('rewrite') or '').strip()
    if len(rewrite) > 200: rewrite = rewrite[:197].rsplit(' ', 1)[0] + '…'
    accent = GREEN if str(c.get('dimension', '')).lower() == 'green' else AMBER

    head = Table([[Paragraph('MOST MATERIAL FINDING', ParagraphStyle('mmf_lbl', parent=STY['score_lbl'], textColor=accent)),
                   Paragraph(esc(risk), ParagraphStyle('mmf_r', parent=STY['small_b'], fontSize=9.6, textColor=risk_color(risk), alignment=TA_RIGHT))]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 32) * 0.7, (PAGE_W - 2 * MARGIN - 32) * 0.3])
    head.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    rows = [head,
            Paragraph(esc(typ), ParagraphStyle('mmf_typ', parent=STY['body'], fontSize=11, fontName='Helvetica-Bold', textColor=NAVY)),
            Spacer(1, 4),
            Paragraph(f'<font color="#8b9baa">Source:</font> {esc(src)}', STY['small']),
            Spacer(1, 4),
            Paragraph(highlight(text, terms), STY['quote'])]
    if why:
        rows.append(Spacer(1, 4))
        rows.append(Paragraph(f'<font color="#174e78"><b>WHY IT MATTERS</b></font> {esc(why)}',
                               ParagraphStyle('mmf_why', parent=STY['small'], leading=10.5)))
    if rewrite:
        rows.append(Spacer(1, 4))
        rows.append(Paragraph(f'<font color="#276749"><b>RECOMMENDED WORDING</b></font> {esc(rewrite)}',
                               ParagraphStyle('mmf_rw', parent=STY['small'], leading=10.5, textColor=INK)))
    inner = Table([[r] for r in rows], colWidths=[PAGE_W - 2 * MARGIN - 32])
    inner.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
    wrap = Table([[inner]], colWidths=[PAGE_W - 2 * MARGIN])
    wrap.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 12), ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('BOX', (0, 0), (-1, -1), 0.8, accent), ('LINEBEFORE', (0, 0), (0, 0), 4, accent),
        ('BACKGROUND', (0, 0), (-1, -1), GREEN_SOFT if accent == GREEN else AMBER_SOFT),
    ]))
    return wrap


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
    text = select_display_excerpt(text, matched_phrase, 320)
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

    head = Table([[Paragraph(esc(typ), ParagraphStyle('pct', parent=STY['small_b'], fontSize=9.6, textColor=NAVY)),
                   Paragraph(esc(risk), ParagraphStyle('rp2', parent=STY['small_b'], fontSize=9.6, textColor=risk_color(risk), alignment=TA_RIGHT))]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 40) * 0.7, (PAGE_W - 2 * MARGIN - 40) * 0.3])
    head.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    rows = [head, Paragraph(f'<font color="#8b9baa">Source:</font> {esc(src)}', STY['small'])]
    rows.append(Spacer(1, 2))
    rows.append(Paragraph(highlight(text, terms), STY['quote']))
    rows.append(Spacer(1, 3))

    # v57t: "Why it matters" and "Evidence gap" side by side instead of stacked -- two shorter
    # facts read faster as a pair than as three consecutive full-width paragraphs, and it keeps
    # the card noticeably shorter.
    why_p = Paragraph(f'<font color="#174e78"><b>WHY IT MATTERS</b></font><br/>{esc(why)}', ParagraphStyle('why', parent=STY['small'], leading=10.5)) if why else Paragraph('', STY['small'])
    gap_p = Paragraph(f'<font color="#6b4e00"><b>EVIDENCE GAP</b></font><br/>{esc(gap)}', ParagraphStyle('gap', parent=STY['small'], leading=10.5))
    half_w = (PAGE_W - 2 * MARGIN - 20 - 10) / 2
    wg = Table([[why_p, gap_p]], colWidths=[half_w, half_w])
    wg.setStyle(TableStyle([('LEFTPADDING', (0, 0), (0, -1), 0), ('RIGHTPADDING', (0, 0), (0, -1), 10),
                             ('LEFTPADDING', (1, 0), (1, -1), 10), ('RIGHTPADDING', (1, 0), (1, -1), 0),
                             ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                             ('LINEBEFORE', (1, 0), (1, -1), 0.5, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    rows.append(wg)

    if rewrite:
        rows.append(Spacer(1, 2))
        rows.append(Paragraph(f'<font color="#276749"><b>RECOMMENDED WORDING</b></font> {esc(rewrite)}',
                               ParagraphStyle('rw3', parent=STY['small'], leading=10, textColor=INK)))
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
    # v58a: the #1 claim is already shown in full on page 1 (Most Material Finding spotlight) --
    # repeating the identical quote, "why it matters" and "recommended wording" verbatim as the
    # first priority-claim card on page 2 read as accidental duplication, not a deliberate
    # summary-then-detail structure, and wasted roughly a third of page 2 on content that added
    # nothing new. Page 2 now covers claims #2 and #3 only; "Top risk drivers" (page 1) still
    # lists all three as a compact headline, so materiality coverage across the two pages is
    # unchanged -- only the wasteful verbatim repeat is removed.
    page2_claims = priority_claims[1:]
    sources = {(c.get('source_label') or c.get('source_url') or '') for c in page2_claims}
    shared_source = len(sources) == 1 and page2_claims
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

    # v57t: Executive conclusion leads the page (matches the reviewer's template order: header ->
    # conclusion -> score block -> top risk drivers), styled as a headline rather than another
    # small boxed card, so a reader gets the "so what" before the supporting numbers.
    page1.append(executive_conclusion_block(data, who))
    page1.append(Spacer(1, 5))

    page1.append(Paragraph('SCORE SUMMARY', ParagraphStyle('ss_lbl', parent=STY['score_lbl'], fontSize=8.5, textColor=NAVY, spaceAfter=4)))
    gauge_wrap = Table([[risk_gauge('GLOBAL CLAIMS RISK', data.get('global_score', data.get('overall_score')),
                                     data.get('global_risk', data.get('overall_risk')))]],
                        colWidths=[PAGE_W - 2 * MARGIN])
    gauge_wrap.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 11), ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fbfcfe')),
    ]))
    page1.append(gauge_wrap)
    page1.append(Spacer(1, 8))
    gs_box_w = (PAGE_W - 2 * MARGIN - 8) / 2
    gs_row = Table([[score_box('Green claims risk', data.get('green_score'), data.get('green_risk'), gs_box_w),
                      score_box('Social claims risk', data.get('social_score'), data.get('social_risk'), gs_box_w)]],
                    colWidths=[gs_box_w, gs_box_w])
    gs_row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                                 ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    page1.append(gs_row)
    page1.append(Spacer(1, 8))
    page1.append(entity_context_and_confidence_row(data))
    page1.append(Spacer(1, 9))

    page1.append(section_card('Top risk drivers', top_risk_drivers_flow(data, 3)))
    page1.append(Spacer(1, 10))

    # v57z: replaces the earlier "Immediate next steps" teaser (a title-only pointer to page 2,
    # which read as filler rather than substance) with the single most material finding shown in
    # full -- exact quote, source and recommended wording. This is genuine, board-relevant content
    # in its own right, not a device to occupy space, and it also fixes the measured ~265pt of
    # empty page-1 real estate below the risk-drivers card in earlier versions.
    page1.append(most_material_finding_spotlight(priority_claims[0] if priority_claims else None))

    # ---------- PAGE 2: Findings and actions ----------
    page2 = []
    page2 += header_block(data, 'Findings and actions',
                           'Priority claims, external signals and recommended next steps', company_name)

    claims_title = ('Additional priority claims (#2\u2013#3 of top 3 by materiality \u2014 #1 featured on page 1)'
                     if len(priority_claims) > 1 else
                     ('Priority claims' if priority_claims else 'Priority claims'))
    page2.append(Paragraph(esc(claims_title), STY['h3']))
    page2.append(Spacer(1, 3))
    if shared_source:
        src_label = (page2_claims[0].get('source_label') or page2_claims[0].get('source_url') or '')[:90]
        page2.append(Paragraph(f'<font color="#8b9baa">All claims below are from:</font> {esc(src_label)}', STY['small']))
        page2.append(Spacer(1, 3))
    if page2_claims:
        for c in page2_claims:
            page2.append(priority_claim_card(c))
            page2.append(Spacer(1, 2))
    elif not priority_claims:
        page2.append(Paragraph('<i>No material problematic claim signal was retained in this scan.</i>', STY['small']))
    else:
        page2.append(Paragraph('<i>Only one material claim was retained in this scan \u2014 see the Most Material Finding on page 1 for full detail.</i>', STY['small']))
    page2.append(Spacer(1, 4))

    HALF_W2 = (PAGE_W - 2 * MARGIN - 8) / 2
    if ext:
        ext_flow = []
        for x in ext:
            title_line = f'<b>{esc(x.get("title") or "External signal")}</b>'
            if x.get('status'): title_line += f'  <font color="#8b9baa" size=7.2>&middot; {esc(x.get("status"))}</font>'
            ext_flow.append(Paragraph(title_line, STY['small_b']))
            if x.get('url'):
                ext_flow.append(Paragraph(f'<font color="#174e78" size=7.2>{esc(x.get("url", "")[:70])}</font>', STY['small']))
            ext_flow.append(Paragraph(esc((x.get('content') or '')[:130]), STY['small']))
            if x.get('related_articles_count', 1) > 1:
                ext_flow.append(Paragraph(f'<font color="#8b9baa" size=7.2>+{x.get("related_articles_count")-1} related article(s).</font>', STY['small']))
            ext_flow.append(Spacer(1, 3))
    else:
        ext_flow = [Paragraph(f'<i>No external public-source signal retained for {esc(who)}, or external search not configured (see Confidence, page 1).</i>', STY['small'])]

    if actions:
        act_flow = []
        for i, a in enumerate(actions, 1):
            act_flow.append(Paragraph(f'<b>{i}. {esc(a.get("title") or "")}</b>', STY['small_b']))
            txt = re.sub(r'\s+', ' ', str(a.get('action') or '')).strip()
            if len(txt) > 130:
                txt = txt[:127].rsplit(' ', 1)[0] + '…'
            act_flow.append(Paragraph(esc(txt), STY['small']))
            act_flow.append(Spacer(1, 3))
    else:
        act_flow = [Paragraph('<b>1. Review retained claim signals</b>', STY['small_b']),
                    Paragraph('Attach evidence, scope and approval records to each claim before reuse.', STY['small'])]

    bottom_row = Table([[section_card('External signals (max 2)', ext_flow, HALF_W2),
                          section_card(f'Priority actions for {who}' if who != 'This company' else 'Priority actions', act_flow, HALF_W2)]],
                        colWidths=[(PAGE_W - 2 * MARGIN) / 2] * 2)
    bottom_row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                     ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                                     ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    page2.append(bottom_row)
    page2.append(Spacer(1, 4))

    # v58a: genuine content to fill the space freed up by removing the page-1/page-2 claim
    # duplication -- and directly what the reviewer originally asked for ("7 pages reviewed
    # across 2 domains..."), previously only implied by the header's page/domain count. Listing
    # the actual pages reviewed lets a reader (or an auditor) see precisely what was and was not
    # covered by this scan, which the header's summary count alone cannot show.
    pages_reviewed = (data.get('report') or {}).get('pages_reviewed') or []
    cd = data.get('crawl_diagnostics') or {}
    if pages_reviewed:
        cov_items = []
        for p in pages_reviewed[:8]:
            short = p if len(p) <= 95 else p[:92] + '…'
            cov_items.append(f'&bull;&nbsp; {esc(short)}')
        if len(pages_reviewed) > 8:
            cov_items.append(f'&bull;&nbsp; <i>+ {len(pages_reviewed) - 8} more page(s)</i>')
        cov_text = '<br/>'.join(cov_items)
        if cd.get('pages_failed'):
            cov_text += (f'<br/><font color="#8b9baa">{cd.get("pages_failed")} additional page fetch attempt(s) '
                         f'could not be accessed and are not reflected above.</font>')
        page2.append(section_card('Coverage & sources reviewed', Paragraph(cov_text, ParagraphStyle('cov', parent=STY['small'], leading=11.5))))
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
