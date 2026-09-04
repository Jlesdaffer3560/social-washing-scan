"""Durably scan-history batch summary report (v93.17).

Builds a single PDF summarising a set of selected /history scans -- executive
summary cards, a written analysis, a risk-distribution chart, a highest-risk-
companies chart, a most-frequently-flagged-claims table, and the full ranked
company data table. Reuses the color palette, typography and footer
conventions from report_pdf.py (the per-company report) so both PDF types
read as one product, without duplicating that styling.

Charts and risk badges are hand-drawn with reportlab.graphics.shapes (rounded
bars, pill badges) rather than the stock reportlab chart widgets, which read
as dated/spreadsheet-like out of the box -- see _rounded_bar()/_pill().

Input rows are exactly what app.py's _v92_fetch_all_for_export() returns: a
list of dicts keyed by _V92_EXPORT_COLUMNS (company, sector, global_score,
global_risk, green_score, social_score, findings_count, scanned_at, ...).

meta (optional dict) may carry:
  'generated'   -- date-string override (mainly for deterministic tests)
  'top_claims'  -- list of dicts (phrase/risk/occurrences/companies/blacklisted),
                   already scoped by the caller to just this selection's scans
                   (app.py's _v92_fetch_top_claims_for_scan_ids()).
"""
from __future__ import annotations

import io

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from report_pdf import (
    CONTENT_W, GREY_100, GREY_300, GREY_500, GREY_700, GREY_900, MARGIN_BOTTOM, MARGIN_TOP,
    MARGIN_X, NAVY, PAGE_W, RED, ST, TEAL_DARK, WHITE, bounded_text, clean_text, esc,
    risk_color, risk_soft,
)

_RISK_ORDER = ['Low', 'Medium', 'High', 'Very high']


def _risk_bucket(risk):
    r = clean_text(risk)
    return r if r in _RISK_ORDER else 'Low'


def _aggregate(rows):
    """Pure aggregation over the row dicts -- kept standalone so it's testable
    without generating a PDF."""
    scores = {'global': [], 'green': [], 'social': []}
    risk_counts = {k: 0 for k in _RISK_ORDER}
    sector_risk_counts = {}
    findings_counts = []
    blacklisted_companies = 0
    high_risk_findings = 0
    dates = []
    for r in rows:
        for dim in ('global', 'green', 'social'):
            v = r.get(f'{dim}_score')
            if isinstance(v, (int, float)):
                scores[dim].append(v)
        risk_counts[_risk_bucket(r.get('global_risk'))] += 1
        sr = clean_text(r.get('sector_risk'))
        if sr:
            sector_risk_counts[sr] = sector_risk_counts.get(sr, 0) + 1
        if (r.get('empco_blacklisted_count') or 0) > 0:
            blacklisted_companies += 1
        high_risk_findings += r.get('high_risk_findings_count') or 0
        fc = r.get('findings_count')
        if isinstance(fc, (int, float)):
            findings_counts.append(fc)
        d = clean_text(r.get('scanned_at'))
        if d:
            dates.append(d[:10])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    scored = [r for r in rows if isinstance(r.get('global_score'), (int, float))]
    top_company = max(scored, key=lambda r: r['global_score']) if scored else None
    bottom_company = min(scored, key=lambda r: r['global_score']) if len(scored) > 1 else None

    dominant_sector_risk = None
    if sector_risk_counts:
        name, count = max(sector_risk_counts.items(), key=lambda kv: kv[1])
        dominant_sector_risk = {'level': name, 'count': count}

    return {
        'total': len(rows),
        'avg_global': avg(scores['global']),
        'avg_green': avg(scores['green']),
        'avg_social': avg(scores['social']),
        'avg_findings': avg(findings_counts),
        'risk_counts': risk_counts,
        'high_plus': risk_counts['High'] + risk_counts['Very high'],
        'blacklisted_companies': blacklisted_companies,
        'high_risk_findings': high_risk_findings,
        'date_range': (min(dates), max(dates)) if dates else (None, None),
        'top_company': top_company,
        'bottom_company': bottom_company,
        'dominant_sector_risk': dominant_sector_risk,
    }


# ---------------------------------------------------------------------------
# Hand-drawn primitives -- rounded bars and pill badges read as a modern
# dashboard rather than a 1990s spreadsheet chart, which the stock reportlab
# chart widgets (VerticalBarChart/HorizontalBarChart) unavoidably look like.
# ---------------------------------------------------------------------------

def _pill(text, bg, fg, width=64, height=15, font_size=7.6):
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, rx=height / 2, ry=height / 2, fillColor=bg, strokeColor=None))
    d.add(String(width / 2, height / 2 - font_size * .34, text, textAnchor='middle',
                  fontName='Helvetica-Bold', fontSize=font_size, fillColor=fg))
    return d


def _risk_pill(risk, width=64):
    risk = clean_text(risk)
    if not risk:
        return Paragraph('&mdash;', ST['table'])
    return _pill(risk, risk_soft(risk), risk_color(risk), width=width)


def _yes_no_pill(flag, width=40):
    if not flag:
        return Paragraph('&mdash;', ST['table'])
    return _pill('Yes', risk_soft('High'), risk_color('High'), width=width)


def _risk_distribution_chart(risk_counts, width, height=140):
    """A hand-drawn, rounded-top vertical bar chart -- one bar per risk tier, the value
    printed above the bar and the tier name below it, no axis/gridlines clutter."""
    d = Drawing(width, height)
    margin_l, margin_r = 14, 14
    margin_b, margin_t = 20, 26
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_b - margin_t
    n = len(_RISK_ORDER)
    slot_w = plot_w / n
    bar_w = slot_w * 0.5
    max_val = max(risk_counts.values()) if risk_counts else 0
    d.add(Line(margin_l, margin_b, width - margin_r, margin_b, strokeColor=GREY_300, strokeWidth=0.75))
    for i, cat in enumerate(_RISK_ORDER):
        val = risk_counts.get(cat, 0)
        cx = margin_l + slot_w * i + slot_w / 2
        bar_h = (val / max_val) * plot_h if max_val else 0
        color = risk_color(cat)
        if val > 0:
            r = min(bar_w / 2, 6)
            d.add(Rect(cx - bar_w / 2, margin_b, bar_w, max(bar_h, r), rx=r, ry=r,
                        fillColor=color, strokeColor=None))
        d.add(String(cx, margin_b + bar_h + 6, str(val), textAnchor='middle',
                      fontName='Helvetica-Bold', fontSize=11, fillColor=NAVY))
        d.add(String(cx, margin_b - 13, cat, textAnchor='middle',
                      fontName='Helvetica-Bold', fontSize=8.5, fillColor=GREY_700))
    return d


def _top_companies_chart(rows, width, top_n=10, row_h=22):
    """A hand-drawn horizontal 'leaderboard' -- capsule-shaped bars scaled to a fixed
    0-100 axis, company name right-aligned to the left of the bar, score printed at the
    bar's end, with a faint alternating row background for readability."""
    scored = [r for r in rows if isinstance(r.get('global_score'), (int, float))]
    if not scored:
        return None
    ranked = sorted(scored, key=lambda r: r['global_score'], reverse=True)[:top_n]
    n = len(ranked)
    height = n * row_h + 10
    name_w = 108
    value_w = 42
    bar_area_w = width - name_w - value_w - 12
    d = Drawing(width, height)
    for i, r in enumerate(ranked):
        y_top = height - 6 - i * row_h
        y_bot = y_top - row_h
        if i % 2 == 0:
            d.add(Rect(0, y_bot, width, row_h, fillColor=GREY_100, strokeColor=None))
        name = bounded_text(r.get('company') or '—', 20)
        d.add(String(name_w - 8, y_bot + row_h / 2 - 3, name, textAnchor='end',
                      fontName='Helvetica-Bold', fontSize=8.3, fillColor=GREY_900))
        score = r.get('global_score') or 0
        bar_w = max(2, (score / 100) * bar_area_w)
        bar_h = row_h - 10
        bar_y = y_bot + (row_h - bar_h) / 2
        color = risk_color(r.get('global_risk'))
        # Light guide ticks at 25/50/75/100 behind the bars, drawn once (only on the
        # first/top row) so they read as a shared scale rather than per-row clutter.
        if i == 0:
            for frac in (0.25, 0.5, 0.75, 1.0):
                gx = name_w + frac * bar_area_w
                d.add(Line(gx, 4, gx, height - 4, strokeColor=GREY_300, strokeWidth=0.5))
        d.add(Rect(name_w, bar_y, bar_w, bar_h, rx=bar_h / 2, ry=bar_h / 2,
                    fillColor=color, strokeColor=None))
        d.add(String(name_w + bar_w + 6, y_bot + row_h / 2 - 3, f'{score}/100',
                      fontName='Helvetica-Bold', fontSize=8.3, fillColor=NAVY))
    return d


def _metric_card(label, value, accent, note='', card_width=None):
    card_width = card_width or (CONTENT_W * .25 - 4)
    inner_width = card_width - 14
    rows = [[Paragraph(esc(str(label).upper()), ST['card_label'])],
            [Paragraph(esc(str(value)), ST['card_num'])]]
    if note:
        rows.append([Paragraph(esc(note), ST['source'])])
    inner = Table(rows, colWidths=[inner_width])
    inner.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
    card = Table([[inner]], colWidths=[card_width])
    card.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .6, GREY_300), ('LINEBEFORE', (0, 0), (0, 0), 3, accent),
                               ('BACKGROUND', (0, 0), (-1, -1), GREY_100),
                               ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                               ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    return card


def _cards_row(agg):
    total = agg['total']
    avg_g = agg['avg_global']
    high_plus = agg['high_plus']
    blacklisted = agg['blacklisted_companies']
    cards = [
        _metric_card('Companies included', total, NAVY),
        _metric_card('Avg. global score', f'{avg_g}/100' if avg_g is not None else '—', TEAL_DARK),
        _metric_card('High / very high risk', f'{high_plus} of {total}' if total else '0',
                      RED if high_plus else risk_color('Low')),
        _metric_card('EmpCo blacklisted', blacklisted, RED if blacklisted else risk_color('Low')),
    ]
    t = Table([cards], colWidths=[CONTENT_W * .25] * 4)
    t.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return t


def _executive_summary_text(agg):
    total = agg['total']
    if not total:
        return 'No scans matched this selection.'
    high_plus = agg['high_plus']
    pct = round(100 * high_plus / total) if total else 0
    avg_g = agg['avg_global']
    parts = [f'Of the {total} compan{"y" if total == 1 else "ies"} included in this report, '
             f'{high_plus} ({pct}%) carr{"y" if high_plus != 1 else "ies"} a High or Very high '
             f'claim-risk rating.']
    if avg_g is not None:
        parts.append(f'The average Global score across the set is {avg_g}/100.')
    if agg['blacklisted_companies']:
        parts.append(f'{agg["blacklisted_companies"]} compan{"y" if agg["blacklisted_companies"] == 1 else "ies"} '
                      f'carr{"y" if agg["blacklisted_companies"] != 1 else "ies"} at least one claim matching a fixed '
                      'EmpCo Annex I blacklisted practice.')
    date_from, date_to = agg['date_range']
    if date_from and date_to:
        parts.append(f'Scans span {date_from} to {date_to}.' if date_from != date_to else f'All scans were run on {date_from}.')
    return ' '.join(parts)


def _analysis_text(agg, top_claims):
    """A somewhat more extensive narrative than the factual Executive Summary: names the
    highest- and lowest-scoring companies for contrast, the dominant sector-risk pattern,
    average findings per company, and the top flagged claim -- whatever data is actually
    available for this selection (each sentence is independently optional)."""
    if not agg['total']:
        return ''
    parts = []
    top = agg.get('top_company')
    if top:
        parts.append(f'{esc(clean_text(top.get("company")) or "The top-scoring company")} carries the highest Global '
                      f'score in this selection, at {top.get("global_score")}/100'
                      + (f' ({esc(clean_text(top.get("global_risk")))})' if top.get('global_risk') else '') + '.')
    bottom = agg.get('bottom_company')
    if bottom and top and bottom is not top:
        parts.append(f'By contrast, {esc(clean_text(bottom.get("company")) or "the lowest-scoring company")} shows the '
                      f'lowest claim risk at {bottom.get("global_score")}/100'
                      + (f' ({esc(clean_text(bottom.get("global_risk")))})' if bottom.get('global_risk') else '') + '.')
    dom = agg.get('dominant_sector_risk')
    if dom and agg['total'] > 1:
        parts.append(f'{dom["count"]} of {agg["total"]} companies operate in a sector classified as '
                      f'{esc(dom["level"])} structural risk.')
    if agg.get('avg_findings') is not None:
        parts.append(f'On average, {agg["avg_findings"]} flagged claim(s) were retained per company.')
    if top_claims:
        tc = top_claims[0]
        phrase = esc(clean_text(tc.get('phrase')))
        occ = tc.get('occurrences') or 0
        comps = tc.get('companies') or 0
        parts.append(f'The most frequently flagged wording across this selection is &ldquo;{phrase}&rdquo;, '
                      f'appearing {occ} time{"s" if occ != 1 else ""} across {comps} compan{"y" if comps == 1 else "ies"}'
                      + (', which also matches a fixed EmpCo blacklisted practice' if tc.get('blacklisted') else '') + '.')
        if len(top_claims) > 1:
            others = ', '.join(f'&ldquo;{esc(clean_text(c.get("phrase")))}&rdquo;' for c in top_claims[1:4])
            parts.append(f'Other recurring wording includes {others}.')
    if not parts:
        return 'No additional pattern stood out beyond what the executive summary above already covers.'
    return ' '.join(parts)


def _top_claims_table(top_claims):
    if not top_claims:
        return None
    header = ['#', 'Phrase', 'Risk level', 'EmpCo blacklist', 'Occurrences', 'Companies']
    data = [[Paragraph(esc(h), ST['table_head']) for h in header]]
    for i, c in enumerate(top_claims):
        data.append([
            Paragraph(str(i + 1), ST['table']),
            Paragraph(esc(bounded_text(c.get('phrase') or '—', 58)), ST['table_dark']),
            _risk_pill(c.get('risk')),
            _yes_no_pill(c.get('blacklisted')),
            Paragraph(esc(c.get('occurrences') if c.get('occurrences') is not None else '—'), ST['table']),
            Paragraph(esc(c.get('companies') if c.get('companies') is not None else '—'), ST['table']),
        ])
    col_widths = [CONTENT_W * .05, CONTENT_W * .36, CONTENT_W * .15, CONTENT_W * .16,
                  CONTENT_W * .14, CONTENT_W * .14]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GREY_100]),
        ('LINEBELOW', (0, 1), (-1, -1), .4, GREY_300),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 1), (3, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return t


def _company_table(rows):
    ranked = sorted(rows, key=lambda r: r.get('global_score') if isinstance(r.get('global_score'), (int, float)) else -1,
                     reverse=True)
    header = ['Company', 'Sector', 'Global', 'Green', 'Social', 'Findings', 'Scanned']
    data = [[Paragraph(esc(h), ST['table_head']) for h in header]]
    for r in ranked:
        gscore = r.get('global_score')
        grisk = r.get('global_risk')
        gcell = Table([[Paragraph(esc(gscore if gscore is not None else '—'), ST['table_dark']),
                        _risk_pill(grisk, width=56) if grisk else Paragraph('', ST['table'])]],
                      colWidths=[18, 58])
        gcell.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                    ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        data.append([
            Paragraph(esc(bounded_text(r.get('company') or '—', 42)), ST['table_dark']),
            Paragraph(esc(bounded_text(r.get('sector') or '—', 26)), ST['table']),
            gcell,
            Paragraph(esc(r.get('green_score') if r.get('green_score') is not None else '—'), ST['table']),
            Paragraph(esc(r.get('social_score') if r.get('social_score') is not None else '—'), ST['table']),
            Paragraph(esc(r.get('findings_count') if r.get('findings_count') is not None else '—'), ST['table']),
            Paragraph(esc(clean_text(r.get('scanned_at'))[:10] or '—'), ST['table']),
        ])
    col_widths = [CONTENT_W * .24, CONTENT_W * .17, CONTENT_W * .18, CONTENT_W * .09,
                  CONTENT_W * .09, CONTENT_W * .10, CONTENT_W * .13]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GREY_100]),
        ('LINEBELOW', (0, 1), (-1, -1), .4, GREY_300),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return t


def _section_title(text):
    return Paragraph(esc(text), ST['section'])


def _header(subtitle, generated_label):
    left = [Paragraph('DURABLY SUSTAINABILITY CLAIMS RISK SCAN', ST['brand']), Spacer(1, 1 * mm),
            Paragraph('Scan Summary Report', ST['title']), Paragraph(esc(subtitle), ST['subtitle'])]
    right = [Paragraph('GENERATED', ST['meta_b']), Paragraph(esc(generated_label), ST['meta'])]
    t = Table([[left, right]], colWidths=[CONTENT_W * .64, CONTENT_W * .36])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 1.2, NAVY),
                            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    return [t, Spacer(1, 2 * mm)]


def _draw_footer(canvas, doc):
    page = canvas.getPageNumber()
    canvas.saveState()
    canvas.setStrokeColor(GREY_300)
    canvas.setLineWidth(.5)
    canvas.line(MARGIN_X, 8.5 * mm, PAGE_W - MARGIN_X, 8.5 * mm)
    canvas.setFont('Helvetica-Oblique', 6.5)
    canvas.setFillColor(GREY_500)
    disclaimer = ('Indicative screening only — not legal advice. Aggregated from individually scanned '
                  'companies; verify each result before external use.')
    canvas.drawString(MARGIN_X, 5.4 * mm, disclaimer)
    canvas.drawRightString(PAGE_W - MARGIN_X, 5.4 * mm, f'© Durably · Scan Summary Report · Page {page}')
    canvas.restoreState()


def build_batch_summary_report_pdf(rows, meta=None):
    """rows: list of dicts (app.py's _v92_fetch_all_for_export() shape).
    meta: optional dict -- see module docstring for 'generated' and 'top_claims'."""
    import datetime as _dt
    meta = meta or {}
    rows = rows or []
    top_claims = meta.get('top_claims') or []
    generated = meta.get('generated') or _dt.date.today().isoformat()
    agg = _aggregate(rows)
    subtitle = f'{agg["total"]} selected scan(s) · generated {generated}'
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
                             topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM, allowSplitting=1)
    flow = []
    flow += _header(subtitle, generated)
    if not rows:
        flow.append(Paragraph('No scans matched this selection.', ST['body_dark']))
        doc.build(flow, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
        return buf.getvalue()
    flow.append(_cards_row(agg))
    flow.append(Spacer(1, 5 * mm))
    flow.append(_section_title('Executive summary'))
    flow.append(Paragraph(esc(_executive_summary_text(agg)), ST['body_dark']))
    flow.append(Spacer(1, 3.5 * mm))
    flow.append(_section_title('Analysis'))
    flow.append(Paragraph(_analysis_text(agg, top_claims), ST['body_dark']))
    flow.append(Spacer(1, 5 * mm))
    flow.append(_section_title('Risk distribution'))
    flow.append(_risk_distribution_chart(agg['risk_counts'], CONTENT_W))
    flow.append(PageBreak())
    flow += _header(subtitle, generated)
    top_chart = _top_companies_chart(rows, CONTENT_W)
    if top_chart is not None:
        flow.append(_section_title('Highest-risk companies (top 10 by global score)'))
        flow.append(Spacer(1, 1 * mm))
        flow.append(top_chart)
        flow.append(Spacer(1, 4 * mm))
    claims_table = _top_claims_table(top_claims)
    if claims_table is not None:
        flow.append(_section_title(f'Top {len(top_claims)} most frequently flagged claims/words'))
        flow.append(Paragraph('Across the scans in this selection only.', ST['small']))
        flow.append(Spacer(1, 1.5 * mm))
        flow.append(claims_table)
    flow.append(PageBreak())
    flow.append(_section_title(f'All {agg["total"]} companies · sorted by global score (highest first)'))
    flow.append(Spacer(1, 2 * mm))
    flow.append(_company_table(rows))
    doc.build(flow, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()


if __name__ == '__main__':
    import json
    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else 'batch_report_test_rows.json'
    target = sys.argv[2] if len(sys.argv) > 2 else 'batch_report_test.pdf'
    with open(source, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    with open(target, 'wb') as handle:
        handle.write(build_batch_summary_report_pdf(payload))
