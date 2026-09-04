"""Durably scan-history batch summary report (v93.16).

Builds a single PDF summarising a set of selected /history scans -- executive
summary cards, a written analysis, a risk-distribution chart, a highest-risk-
companies chart, a most-frequently-flagged-claims table, and the full ranked
company data table. Reuses the color palette, typography and footer
conventions from report_pdf.py (the per-company report) so both PDF types
read as one product, without duplicating that styling.

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

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from report_pdf import (
    CONTENT_W, GREY_100, GREY_300, GREY_500, GREY_700, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X,
    NAVY, PAGE_W, RED, ST, TEAL_DARK, WHITE, bounded_text, clean_text, esc, risk_color,
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
        d = clean_text(r.get('scanned_at'))
        if d:
            dates.append(d[:10])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    top_company = None
    scored = [r for r in rows if isinstance(r.get('global_score'), (int, float))]
    if scored:
        top_company = max(scored, key=lambda r: r['global_score'])

    dominant_sector_risk = None
    if sector_risk_counts:
        name, count = max(sector_risk_counts.items(), key=lambda kv: kv[1])
        dominant_sector_risk = {'level': name, 'count': count}

    return {
        'total': len(rows),
        'avg_global': avg(scores['global']),
        'avg_green': avg(scores['green']),
        'avg_social': avg(scores['social']),
        'risk_counts': risk_counts,
        'high_plus': risk_counts['High'] + risk_counts['Very high'],
        'blacklisted_companies': blacklisted_companies,
        'high_risk_findings': high_risk_findings,
        'date_range': (min(dates), max(dates)) if dates else (None, None),
        'top_company': top_company,
        'dominant_sector_risk': dominant_sector_risk,
    }


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
    card.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .6, GREY_300), ('LINEBEFORE', (0, 0), (0, 0), 2.6, accent),
                               ('BACKGROUND', (0, 0), (-1, -1), GREY_100),
                               ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                               ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
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
    t.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return t


def _risk_distribution_chart(risk_counts, width, height=100):
    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 35
    chart.y = 14
    chart.width = width - 55
    chart.height = height - 34
    chart.data = [[risk_counts[k] for k in _RISK_ORDER]]
    chart.categoryAxis.categoryNames = _RISK_ORDER
    chart.categoryAxis.labels.fontSize = 8.5
    chart.categoryAxis.labels.fontName = 'Helvetica-Bold'
    chart.categoryAxis.labels.fillColor = GREY_700
    chart.valueAxis.valueMin = 0
    max_count = max(risk_counts.values()) if risk_counts else 0
    chart.valueAxis.valueMax = max(1, max_count + 1)
    chart.valueAxis.labels.fontSize = 7.5
    chart.valueAxis.labels.fillColor = GREY_500
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = GREY_300
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.bars.strokeColor = None
    chart.barWidth = 0.55
    chart.groupSpacing = 12
    # Value-on-top-of-bar labels -- a nicer, more informative chart than bare bars with
    # only an axis to read the count from.
    chart.barLabelFormat = '%d'
    chart.barLabels.fontName = 'Helvetica-Bold'
    chart.barLabels.fontSize = 9
    chart.barLabels.fillColor = NAVY
    chart.barLabels.dy = 4
    palette = [risk_color(k) for k in _RISK_ORDER]
    for i, c in enumerate(palette):
        chart.bars[(0, i)].fillColor = c
    d.add(chart)
    return d


def _top_companies_chart(rows, width, height=185, top_n=10):
    scored = [r for r in rows if isinstance(r.get('global_score'), (int, float))]
    if not scored:
        return None
    ranked = sorted(scored, key=lambda r: r['global_score'], reverse=True)[:top_n]
    ranked = list(reversed(ranked))  # highest bar drawn at the top
    names = [bounded_text(r.get('company') or '—', 24) for r in ranked]
    values = [r['global_score'] for r in ranked]
    palette = [risk_color(r.get('global_risk')) for r in ranked]
    d = Drawing(width, height)
    chart = HorizontalBarChart()
    chart.x = 95
    chart.y = 10
    chart.width = width - 150
    chart.height = height - 20
    chart.data = [values]
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontSize = 8
    chart.categoryAxis.labels.fontName = 'Helvetica-Bold'
    chart.categoryAxis.labels.fillColor = GREY_700
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.labels.fontSize = 7.5
    chart.valueAxis.labels.fillColor = GREY_500
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = GREY_300
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.bars.strokeColor = None
    chart.barWidth = 7
    chart.barLabelFormat = '%d/100'
    chart.barLabels.fontName = 'Helvetica-Bold'
    chart.barLabels.fontSize = 8
    chart.barLabels.fillColor = NAVY
    chart.barLabels.dx = 4
    chart.barLabels.boxAnchor = 'w'
    for i, c in enumerate(palette):
        chart.bars[(0, i)].fillColor = c
    d.add(chart)
    return d


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
    if not agg['total']:
        return ''
    parts = []
    top = agg.get('top_company')
    if top:
        parts.append(f'{esc(clean_text(top.get("company")) or "The top-scoring company")} carries the highest Global '
                      f'score in this selection, at {top.get("global_score")}/100'
                      + (f' ({esc(clean_text(top.get("global_risk")))})' if top.get('global_risk') else '') + '.')
    dom = agg.get('dominant_sector_risk')
    if dom and agg['total'] > 1:
        parts.append(f'{dom["count"]} of {agg["total"]} companies operate in a sector classified as '
                      f'{esc(dom["level"])} structural risk.')
    if top_claims:
        tc = top_claims[0]
        phrase = esc(clean_text(tc.get('phrase')))
        occ = tc.get('occurrences') or 0
        comps = tc.get('companies') or 0
        parts.append(f'The most frequently flagged wording across this selection is &ldquo;{phrase}&rdquo;, '
                      f'appearing {occ} time{"s" if occ != 1 else ""} across {comps} compan{"y" if comps == 1 else "ies"}'
                      + (', which also matches a fixed EmpCo blacklisted practice' if tc.get('blacklisted') else '') + '.')
    if not parts:
        return 'No additional pattern stood out beyond what the executive summary above already covers.'
    return ' '.join(parts)


def _top_claims_table(top_claims):
    if not top_claims:
        return None
    yes_badge = f'<font color="{RED.hexval()}"><b>Yes</b></font>'
    header = ['#', 'Phrase', 'Risk level', 'EmpCo blacklist', 'Occurrences', 'Companies']
    data = [[Paragraph(esc(h), ST['table_head']) for h in header]]
    for i, c in enumerate(top_claims):
        risk = c.get('risk') or ''
        risk_cell = f'<font color="{risk_color(risk).hexval()}"><b>{esc(risk)}</b></font>' if risk else '—'
        data.append([
            Paragraph(str(i + 1), ST['table']),
            Paragraph(esc(bounded_text(c.get('phrase') or '—', 60)), ST['table_dark']),
            Paragraph(risk_cell, ST['table']),
            Paragraph(yes_badge if c.get('blacklisted') else '&mdash;', ST['table']),
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
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
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
        gcell = esc(gscore if gscore is not None else '—')
        if grisk:
            gcell += f' <font color="{risk_color(grisk).hexval()}"><b>{esc(grisk)}</b></font>'
        data.append([
            Paragraph(esc(bounded_text(r.get('company') or '—', 42)), ST['table_dark']),
            Paragraph(esc(bounded_text(r.get('sector') or '—', 28)), ST['table']),
            Paragraph(gcell, ST['table']),
            Paragraph(esc(r.get('green_score') if r.get('green_score') is not None else '—'), ST['table']),
            Paragraph(esc(r.get('social_score') if r.get('social_score') is not None else '—'), ST['table']),
            Paragraph(esc(r.get('findings_count') if r.get('findings_count') is not None else '—'), ST['table']),
            Paragraph(esc(clean_text(r.get('scanned_at'))[:10] or '—'), ST['table']),
        ])
    col_widths = [CONTENT_W * .25, CONTENT_W * .17, CONTENT_W * .15, CONTENT_W * .09,
                  CONTENT_W * .09, CONTENT_W * .12, CONTENT_W * .13]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('LINEBELOW', (0, 0), (-1, 0), 1, NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GREY_100]),
        ('LINEBELOW', (0, 1), (-1, -1), .4, GREY_300),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
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
    flow.append(Spacer(1, 4 * mm))
    flow.append(_section_title('Executive summary'))
    flow.append(Paragraph(esc(_executive_summary_text(agg)), ST['body_dark']))
    flow.append(Spacer(1, 3 * mm))
    flow.append(_section_title('Analysis'))
    flow.append(Paragraph(_analysis_text(agg, top_claims), ST['body_dark']))
    flow.append(Spacer(1, 4 * mm))
    flow.append(_section_title('Risk distribution'))
    flow.append(_risk_distribution_chart(agg['risk_counts'], CONTENT_W))
    flow.append(PageBreak())
    flow += _header(subtitle, generated)
    top_chart = _top_companies_chart(rows, CONTENT_W)
    if top_chart is not None:
        flow.append(_section_title('Highest-risk companies (top 10 by global score)'))
        flow.append(top_chart)
        flow.append(Spacer(1, 3 * mm))
    claims_table = _top_claims_table(top_claims)
    if claims_table is not None:
        flow.append(_section_title(f'Top {len(top_claims)} most frequently flagged claims/words'))
        flow.append(Paragraph('Across the scans in this selection only.', ST['small']))
        flow.append(Spacer(1, 1 * mm))
        flow.append(claims_table)
    flow.append(PageBreak())
    flow.append(_section_title(f'All {agg["total"]} companies · sorted by global score (highest first)'))
    flow.append(Spacer(1, 1.5 * mm))
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
