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
    return [c for c in rows if is_material(c)][:n]


def header_block(data, page_title, page_sub):
    kicker = Paragraph('DURABLY SUSTAINABILITY SCAN', STY['kicker'])
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


def score_box(label, num, risk):
    color = risk_color(risk)
    inner = Table([
        [Paragraph(label.upper(), STY['score_lbl'])],
        [Paragraph(f'{num if num is not None else "—"}<font size=8 color="#8b9baa">/100</font>', STY['score_num'])],
        [Paragraph(esc(risk or '—'), ParagraphStyle('r', parent=STY['score_risk'], textColor=color))],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 18) / 4])
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
    boxes = [score_box('Global risk score', gs, grs),
             score_box('Green risk score', gns, gnrs),
             score_box('Social risk score', ss, srs),
             score_box('Overall risk level', None, grs)]
    # Overall-risk box shows the risk word large instead of a second number.
    boxes[3] = Table([
        [Paragraph('OVERALL RISK LEVEL', STY['score_lbl'])],
        [Paragraph(esc(grs or '—'), ParagraphStyle('ov', parent=STY['score_num'], fontSize=15, textColor=risk_color(grs)))],
        [Paragraph('Combined green + social', STY['small'])],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 18) / 4])
    boxes[3].setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 7), ('BOTTOMPADDING', (0, -1), (-1, -1), 7),
        ('TOPPADDING', (0, 1), (-1, 1), 1), ('BOTTOMPADDING', (0, 1), (-1, 1), 3),
        ('LINEBEFORE', (0, 0), (0, -1), 3, risk_color(grs)),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff8f8') if risk_color(grs) == DANGER else colors.HexColor('#fbfcfe')),
    ]))
    row = Table([boxes], colWidths=[(PAGE_W - 2 * MARGIN) / 4] * 4)
    row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                              ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return row


def bullet_box(title, items, accent):
    items = [i for i in (items or []) if i][:4]
    body = '<br/>'.join('&bull;&nbsp; ' + esc(i) for i in items) if items else '<i>No specific red flag retained.</i>'
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


def claim_card(c):
    typ = c.get('claim_type') or c.get('type') or 'Claim signal'
    risk = c.get('risk_level') or c.get('risk') or ''
    src = (c.get('source_label') or c.get('source_url') or 'Reviewed material')[:80]
    text = c.get('claim_text') or c.get('claim') or ''
    text = re.sub(r'\s+', ' ', str(text)).strip()
    if len(text) > 125:
        text = text[:122].rsplit(' ', 1)[0] + '…'
    terms = c.get('problematic_terms') or []
    head = Table([[Paragraph(esc(typ), STY['small_b']),
                   Paragraph(esc(risk), ParagraphStyle('rp', parent=STY['small_b'], textColor=risk_color(risk), alignment=TA_RIGHT))]],
                 colWidths=[(PAGE_W - 2 * MARGIN - 40) * 0.7, (PAGE_W - 2 * MARGIN - 40) * 0.3])
    head.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    src_p = Paragraph(f'<font color="#8b9baa">Source:</font> {esc(src)}', STY['small'])
    quote_p = Paragraph(highlight(text, terms), STY['quote'])
    trig = ' &middot; '.join(f'<b backColor="#fff1a8">{esc(t)}</b>' for t in terms[:5]) or 'Pattern-based signal'
    trig_p = Paragraph(f'<font color="#6b4e00"><b>Trigger:</b></font> {trig}', STY['small'])
    accent = GREEN if str(c.get('dimension', '')).lower() == 'green' else AMBER
    inner = Table([[head], [src_p], [quote_p], [trig_p]], colWidths=[PAGE_W - 2 * MARGIN - 20])
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


def claim_section(title, rows):
    flow = [Paragraph(esc(title), STY['h3']), Spacer(1, 3)]
    if not rows:
        flow.append(Paragraph('<i>No material problematic claim signal retained.</i>', STY['small']))
        return flow
    for r in rows:
        flow.append(claim_card(r))
        flow.append(Spacer(1, 1.5))
    return flow


def driver_table(comp):
    comp = comp or {}
    rows = [['Score component', 'Weight', 'Value/100'],
            ['Claim wording severity', '42%', str(comp.get('claim_wording_risk', '—'))],
            ['Evidence / substantiation gap', '24%', str(comp.get('substantiation_risk', '—'))],
            ['External stakeholder context', '22%', str(comp.get('external_context_risk', '—'))],
            ['Sector & channel sensitivity', '12%', str(comp.get('sector_baseline_risk', '—'))]]
    data = [[Paragraph(esc(rows[0][0]), STY['small_b']), Paragraph(esc(rows[0][1]), STY['small_b']), Paragraph(esc(rows[0][2]), STY['small_b'])]]
    for r in rows[1:]:
        data.append([Paragraph(esc(r[0]), STY['small']), Paragraph(esc(r[1]), STY['small']),
                     Paragraph(esc(r[2]), ParagraphStyle('v', parent=STY['small_b'], textColor=NAVY, alignment=TA_RIGHT))])
    w = (PAGE_W - 2 * MARGIN - 10) / 2
    t = Table(data, colWidths=[w * 0.56, w * 0.2, w * 0.24])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SOFT),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, LINE),
        ('LINEBELOW', (0, 1), (-1, -2), 0.4, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    return t


def section_card(title, content):
    body = [Paragraph(esc(title), STY['h3']), Spacer(1, 3)] + (content if isinstance(content, list) else [content])
    tbl = Table([[body]], colWidths=[PAGE_W - 2 * MARGIN])
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


def build_company_report_pdf(data):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                             topMargin=MARGIN, bottomMargin=MARGIN + 6)

    flags = data.get('red_flags_by_dimension') or {}
    green_claims = top_claims(data, 'Green', 3)
    social_claims = top_claims(data, 'Social', 3)
    actions = (data.get('company_action_plan') or [])[:4]
    ext = ((data.get('external_research', {}).get('green', {}).get('targeted_negative_sources') or []) +
           (data.get('external_research', {}).get('social', {}).get('targeted_negative_sources') or []) +
           (data.get('external_research', {}).get('targeted_negative_sources') or []))[:3]
    gc = (data.get('score_components') or {}).get('green') or {}
    sc = (data.get('score_components') or {}).get('social') or {}

    # ---------- PAGE 1 ----------
    page1 = []
    page1 += header_block(data, 'Company claim-risk report',
                           'EmpCo · EU Green Claims Directive · EU Forced Labour Regulation · EUDR')
    page1.append(scores_row(data))
    page1.append(Spacer(1, 7))
    page1.append(section_card('Executive summary', Paragraph(
        esc(data.get('assessment_summary_specific') or (data.get('report') or {}).get('summary') or 'No summary available.'),
        STY['body'])))
    page1.append(Spacer(1, 5))
    flagrow = Table([[bullet_box('Green claim red flags', flags.get('green'), GREEN),
                       bullet_box('Social claim red flags', flags.get('social'), AMBER)]],
                     colWidths=[(PAGE_W - 2 * MARGIN) / 2] * 2)
    flagrow.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                  ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    page1.append(flagrow)
    page1.append(Spacer(1, 5))
    page1 += claim_section('Key green claim signals retained', green_claims)
    page1.append(Spacer(1, 3))
    page1 += claim_section('Key social claim signals retained', social_claims)

    # ---------- PAGE 2 ----------
    page2 = []
    page2 += header_block(data, 'Evidence, external signals & action plan',
                           'Claim-risk score drivers and recommended next steps')
    driverrow = Table([[section_card('Green score drivers', driver_table(gc)),
                         section_card('Social score drivers', driver_table(sc))]],
                       colWidths=[(PAGE_W - 2 * MARGIN) / 2] * 2)
    driverrow.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                    ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    page2.append(driverrow)
    page2.append(Spacer(1, 4))

    if ext:
        ext_flow = []
        for x in ext:
            ext_flow.append(Paragraph(f'<b>{esc(x.get("title") or "External signal")}</b>', STY['small_b']))
            if x.get('url'):
                ext_flow.append(Paragraph(f'<font color="#174e78">{esc(x.get("url", "")[:100])}</font>', STY['small']))
            ext_flow.append(Paragraph(esc((x.get('content') or '')[:200]), STY['small']))
            ext_flow.append(Spacer(1, 4))
    else:
        ext_flow = [Paragraph('<i>No negative external stakeholder signal retained, or external search not configured.</i>', STY['small'])]
    page2.append(section_card('Negative external stakeholder signals retained', ext_flow))
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
    page2.append(section_card('Recommended actions', act_flow))
    page2.append(Spacer(1, 4))

    bands = [['Score range', 'Meaning'],
              ['0–44  Low', 'No material problematic claim or limited wording risk.'],
              ['45–74  Medium', 'Some claim signals, wording risk or evidence gaps for review.'],
              ['75–89  High', 'Strong wording risk, evidence gaps or negative external signals.'],
              ['90–100  Very high', 'Multiple severe signals with regulatory or external context.']]
    band_colors = [None, GREEN, AMBER, DANGER, colors.HexColor('#7a1e1e')]
    bdata = [[Paragraph(esc(bands[0][0]), STY['small_b']), Paragraph(esc(bands[0][1]), STY['small_b'])]]
    for i, r in enumerate(bands[1:], 1):
        bdata.append([Paragraph(esc(r[0]), ParagraphStyle(f'b{i}', parent=STY['small_b'], textColor=band_colors[i])),
                       Paragraph(esc(r[1]), STY['small'])])
    band_w = (PAGE_W - 2 * MARGIN - 10) / 2
    btbl = Table(bdata, colWidths=[band_w * 0.4, band_w * 0.6])
    btbl.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), SOFT), ('LINEBELOW', (0, 0), (-1, 0), 0.6, LINE),
                               ('LINEBELOW', (0, 1), (-1, -2), 0.4, LINE),
                               ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                               ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    method_note = Paragraph(
        'Claim wording (42%) + Evidence gap (24%) + External context (22%) + Sector/channel sensitivity (12%). '
        'Lenses: EmpCo &bull; EU Green Claims Directive &bull; EU Forced Labour Regulation (EU) 2024/3015 &bull; EUDR. '
        'CSDDD and CSRD thresholds reflect the post-Omnibus I scope (Directive 2026/470, in force 18 March 2026).', STY['small'])
    lastrow = Table([[section_card('Score interpretation', btbl), section_card('Methodology note', method_note)]],
                     colWidths=[(PAGE_W - 2 * MARGIN) / 2] * 2)
    lastrow.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                  ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    page2.append(lastrow)

    flowables = page1 + [PageBreak()] + page2

    def on_page1(c, d):
        footer(c, d, '© Durably · Page 1 of 2')

    def on_page2(c, d):
        footer(c, d, '© Durably · Page 2 of 2')

    doc.build(flowables, onFirstPage=on_page1, onLaterPages=on_page2)
    return buf.getvalue()


if __name__ == '__main__':
    import json
    data = json.load(open('/tmp/scan_result.json'))
    pdf_bytes = build_company_report_pdf(data)
    open('/tmp/company_report_test.pdf', 'wb').write(pdf_bytes)
    print('Generated', len(pdf_bytes), 'bytes')
