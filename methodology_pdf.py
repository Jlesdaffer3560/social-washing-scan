"""Generates methodology.pdf: the static methodology summary document.
Rebuilt to reflect the scan's actual scope (EmpCo + EU Forced Labour Regulation only)
and to match the score bands the live scan actually produces.
Visual style matches report_pdf.py (same palette/typography), consistent with the
original methodology.pdf.
"""
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle

NAVY = colors.HexColor('#173f5f')
INK = colors.HexColor('#132033')
MUTED = colors.HexColor('#5e6b7d')
LINE = colors.HexColor('#dfe5ee')
SOFT = colors.HexColor('#f6f8fb')
ACCENT = colors.HexColor('#265f5c')
GREEN = colors.HexColor('#276749')
AMBER = colors.HexColor('#9b6a17')
DANGER = colors.HexColor('#a43c3c')

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm

def _style(name, **kw):
    base = dict(fontName='Helvetica', fontSize=8.5, leading=11.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)

STY = {
    'title': _style('title', fontName='Helvetica-Bold', fontSize=18, textColor=NAVY, leading=21),
    'sub': _style('sub', fontSize=10, textColor=MUTED, leading=13),
    'tag': _style('tag', fontSize=9, textColor=INK, leading=12.5),
    'tagsmall': _style('tagsmall', fontSize=8.5, textColor=MUTED, leading=11.5),
    'intro': _style('intro', fontSize=9, leading=12.5),
    'h2': _style('h2', fontName='Helvetica-Bold', fontSize=11.7, textColor=NAVY, leading=14, spaceBefore=9, spaceAfter=4),
    'body': _style('body', fontSize=8.5, leading=12),
    'th': _style('th', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white, leading=10.5),
    'td_b': _style('td_b', fontName='Helvetica-Bold', fontSize=8, textColor=NAVY, leading=11),
    'td': _style('td', fontSize=8, leading=11),
    'note_b': _style('note_b', fontName='Helvetica-Bold', fontSize=8.5, leading=11.5),
    'foot': _style('foot', fontName='Helvetica-Oblique', fontSize=7.8, leading=10.5, textColor=MUTED),
}

def esc(s):
    return str(s)

def section_table(rows, col_widths, header_bg=NAVY):
    """rows[0] is the header row (plain strings), rest are (Paragraph, Paragraph, ...)."""
    data = [[Paragraph(esc(h), STY['th']) for h in rows[0]]]
    for r in rows[1:]:
        data.append(list(r))
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, header_bg),
        ('LINEBELOW', (0, 1), (-1, -1), 0.4, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return t

def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(.5)
    canvas.line(MARGIN, 9 * mm, PAGE_W - MARGIN, 9 * mm)
    canvas.setFont('Helvetica-Oblique', 6.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 5.8 * mm, 'Durably Sustainability Claims Risk Scan — Methodology summary · v72')
    canvas.drawRightString(PAGE_W - MARGIN, 5.8 * mm, f'Page {canvas.getPageNumber()}')
    canvas.restoreState()


def build_methodology_pdf():
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                             topMargin=MARGIN, bottomMargin=MARGIN + 4 * mm)
    W = PAGE_W - 2 * MARGIN
    flow = []

    flow.append(Paragraph('Durably Sustainability Claims Risk Scan', STY['title']))
    flow.append(Paragraph('Methodology summary &mdash; claim-risk screening &middot; v72 &middot; 22 July 2026', STY['sub']))
    flow.append(Spacer(1, 5))
    flow.append(Paragraph(
        'EmpCo / Directive (EU) 2024/825 ("Empowering Consumers for the Green Transition" Directive) '
        '&bull; EU Forced Labour Regulation (Regulation (EU) 2024/3015)', STY['tag']))
    flow.append(Spacer(1, 6))
    flow.append(HRFlowable(width='100%', thickness=1.2, color=NAVY, spaceBefore=0, spaceAfter=8))

    flow.append(Paragraph(
        'This is a claims-risk screening tool, not a legal opinion, certification or assurance. It identifies '
        'sustainability wording that may be too broad or insufficiently evidenced, may fall within consumer-facing '
        'EmpCo rules, may create forced-labour-related assurance risk, or may be contradicted by relevant external public-source context.',
        STY['intro']))

    flow.append(Paragraph('1. Purpose and regulatory lenses', STY['h2']))
    flow.append(Paragraph(
        'The scan applies exactly two regulatory lenses. Broader responsible-business frameworks (OECD Guidelines, '
        'UN Guiding Principles, ILO, GRI) are used only as supporting substantiation criteria for social claims, '
        'not as separate scored lenses.', STY['body']))
    flow.append(Spacer(1, 5))
    lens_rows = [
        ('Lens', 'How it is used in the scan'),
        (Paragraph('<b>EmpCo</b> / Directive (EU) 2024/825', STY['td_b']),
         Paragraph('Main green-claims lens, and also covers social characteristics: Art. 6(1)(b), as amended, brings '
                   '"environmental or social characteristics" (wages, safety, human rights, equal treatment, gender '
                   'equality, inclusion, diversity) within the same misleading-claims test. "EmpCo" stands for the '
                   'Directive as regards <b>Emp</b>owering <b>Co</b>nsumers for the green transition (Directive (EU) '
                   '2024/825). Member States transpose by 27 March 2026; rules apply from 27 September 2026. '
                   'Prioritises generic environmental claims, climate-neutrality/offsetting claims, self-declared '
                   'sustainability labels, broad absolute wording, future environmental-performance claims, comparative '
                   'claims, and legal compliance presented as a sustainability benefit.', STY['td'])),
        (Paragraph('<b>EU Forced Labour Regulation</b> / Regulation (EU) 2024/3015', STY['td_b']),
         Paragraph('Main forced-labour and supply-chain assurance lens. A product-market-access and customs-enforcement regime, not a claims law: '
                   'Art. 1(3) confirms it creates no new due-diligence obligation of its own. Flags wording that may '
                   'imply products, suppliers or value chains are free from forced labour, or that traceability, due '
                   'diligence or import/export controls provide assurance beyond what is evidenced. Core prohibition '
                   'and enforcement provisions apply from 14 December 2027 (a few governance articles already apply '
                   'from 13 December 2024).', STY['td'])),
        (Paragraph('UCPD environmental-claim definition', STY['td_b']),
         Paragraph('Supports the EmpCo lens: checks whether text, images, symbols, labels, brand names or presentation '
                   'imply positive, zero, reduced, comparative or improved environmental impact.', STY['td'])),
        (Paragraph('OECD Guidelines / UNGPs / ILO / GRI', STY['td_b']),
         Paragraph('Supporting substantiation framework for social and forced-labour claims: identification, prevention, '
                   'mitigation and accounting for adverse impacts, checked for specificity, balance and evidence.', STY['td'])),
    ]
    flow.append(section_table(lens_rows, [W * 0.34, W * 0.66]))

    flow.append(Paragraph('2. Potentially prohibited vs. problematic claims (EmpCo legal basis)', STY['h2']))
    flow.append(Paragraph(
        'Every retained green or social claim is also classified by its EmpCo legal basis, shown in the report as a '
        '<b>Potentially Prohibited (Annex I)</b> or <b>Problematic (case-by-case)</b> label. This is a screening indicator, not a '
        'legal finding.', STY['body']))
    flow.append(Spacer(1, 5))
    legal_basis_rows = [
        ('Classification', 'Meaning'),
        (Paragraph('<b>Potentially Prohibited (Annex I)</b>', ParagraphStyle('lb1', parent=STY['td_b'], textColor=DANGER)),
         Paragraph('Falls within the fixed list of practices Annex I of Directive (EU) 2024/825 adds to the UCPD '
                   'blacklist &mdash; sustainability labels not based on a qualifying certification scheme or not established by '
                   'public authorities, generic environmental claims that lack same-medium specification and recognised excellent '
                   'environmental performance, offset-based claims that a specific <b>product</b> has a climate neutral/reduced/'
                   'positive impact, and presenting a legal requirement as a distinguishing sustainability feature. Once EmpCo '
                   'applies (27 September 2026), these practices are automatically unfair if the described conditions are met '
                   '&mdash; no separate case-by-case materiality or consumer-impact test is required. A company- or '
                   'operations-wide neutrality claim, or a generic claim that already carries same-medium specification, falls '
                   'outside this fixed list and is assessed case-by-case instead.', STY['td'])),
        (Paragraph('<b>Problematic (case-by-case)</b>', ParagraphStyle('lb2', parent=STY['td_b'], textColor=AMBER)),
         Paragraph('Not on the Annex I list, but wording that may still be found misleading after an individual '
                   'assessment under general UCPD unfair-commercial-practice rules (Art. 6/7, or Art. 6(2)(d) for '
                   'future environmental-performance claims). Whether it is actually misleading depends on context, '
                   'substantiation and likely consumer impact, and is not determined by this scan.', STY['td'])),
    ]
    flow.append(section_table(legal_basis_rows, [W * 0.26, W * 0.74]))

    flow.append(Paragraph('3. What is retained as a claim signal', STY['h2']))
    flow.append(Paragraph(
        'The scan does not operate as a simple keyword search. A word is retained only when the surrounding wording '
        'appears to make, imply or visually suggest an environmental or social performance claim. Neutral references '
        'such as <i>working with suppliers</i> or <i>backing local suppliers</i> are not retained unless they also imply '
        'assurance, compliance, certification, traceability, audits, due diligence or full supply-chain coverage. '
        'The website check follows relevant on-site links and, where linked directly from the company\'s own site, '
        'reads the text of PDF reports (e.g. an annual, CSR, ESG or sustainability report) in addition to web pages.',
        STY['body']))
    flow.append(Spacer(1, 5))
    signal_rows = [
        ('Retained signal type', 'Examples', 'Why it matters'),
        (Paragraph('Generic environmental claims', STY['td_b']),
         Paragraph('eco-friendly, green choice, sustainable product, conscious collection, planet friendly', STY['td']),
         Paragraph('Can fall under EmpCo restrictions when the claim is not clearly specified or substantiated on the same medium.', STY['td'])),
        (Paragraph('Climate and offsetting claims', STY['td_b']),
         Paragraph('carbon neutral, climate neutral, carbon compensated, net zero product, reduced climate impact', STY['td']),
         Paragraph('Product-level neutrality or reduced-impact claims based on offsetting are high-priority EmpCo risk indicators.', STY['td'])),
        (Paragraph('Labels, badges, icons', STY['td_b']),
         Paragraph('eco label, green badge, certified sustainable, leaf/planet/recycled icons used as trust marks', STY['td']),
         Paragraph('A sustainability label not based on a qualifying certification scheme or not established by public authorities can mislead.', STY['td'])),
        (Paragraph('Supplier / sourcing assurance', STY['td_b']),
         Paragraph('responsible sourcing, ethical sourcing, audited suppliers, traceable supply chain, all suppliers comply', STY['td']),
         Paragraph('May imply supply-chain control, audit quality or compliance that must be evidenced with scope, coverage, methodology and remediation.', STY['td'])),
        (Paragraph('Forced-labour assurance', STY['td_b']),
         Paragraph('forced-labour free, modern-slavery free, no forced labour, product traceability', STY['td']),
         Paragraph('Creates substantiation exposure now under general UCPD rules; traceability, risk-assessment, mitigation and remediation evidence may become relevant to enforcement under Regulation (EU) 2024/3015, which does not itself create a standalone due-diligence obligation (Art. 1(3)).', STY['td'])),
        (Paragraph('Aspirational / future social-performance wording', STY['td_b']),
         Paragraph('working towards a foundation for living wages, wish to build a world where human rights are respected, our ambition is...', STY['td']),
         Paragraph('Vague, forward-looking commitments on wages, human rights or working conditions with no baseline, timeline or achieved result. Treated as a relevant social-washing risk indicator on that basis alone -- not as evidence of a specific academic finding about how common or dominant this pattern is in any sector.', STY['td'])),
    ]
    flow.append(section_table(signal_rows, [W * 0.24, W * 0.36, W * 0.40]))

    flow.append(Paragraph('4. Claim source and detected wording', STY['h2']))
    flow.append(Spacer(1, 3))
    field_rows = [
        ('Field in report', 'Meaning'),
        (Paragraph('Source', STY['td_b']), Paragraph('The website page, uploaded document or related checked page where the retained wording was found.', STY['td'])),
        (Paragraph('Exact retained wording', STY['td_b']), Paragraph('A short passage around the claim, normally one sentence. The scan avoids mixing long paragraphs with isolated words.', STY['td'])),
        (Paragraph('Trigger phrase(s)', STY['td_b']), Paragraph('The specific wording that made the passage relevant, for example carbon neutral, eco-friendly, responsible sourcing or forced-labour free.', STY['td'])),
        (Paragraph('Why it matters', STY['td_b']), Paragraph('A short explanation of the EmpCo, Forced Labour Regulation or substantiation risk.', STY['td'])),
        (Paragraph('Suggested improvement', STY['td_b']), Paragraph('A practical rewrite principle: specify scope, evidence, method, time period, conditions and limitations.', STY['td'])),
    ]
    flow.append(section_table(field_rows, [W * 0.28, W * 0.72]))

    flow.append(Paragraph('5. Score calculation', STY['h2']))
    flow.append(Paragraph(
        'The scan produces three scores: <b>Green score</b>, <b>Social score</b> and <b>Global score</b>. Scores are '
        '<b>risk scores, not performance scores</b>. Higher scores indicate higher claim-risk exposure or stronger need '
        'for legal, communication or evidence review.', STY['body']))
    flow.append(Spacer(1, 5))
    driver_rows = [
        ('Component', 'Weight (primary driver)', 'What increases the score'),
        (Paragraph('Claim wording severity', STY['td_b']), Paragraph('Primary driver (42%)', STY['td']),
         Paragraph('Direct EmpCo blacklist indicators (generic claims, offsetting, labels, absolute wording) and '
                   'forced-labour or supplier assurance wording, plus multiple retained material claim signals.', STY['td'])),
        (Paragraph('Evidence-gap risk', STY['td_b']), Paragraph('Important driver (24%)', STY['td']),
         Paragraph('Limited visible substantiation, missing scope, missing methodology, missing dates, missing verification, missing supplier coverage or weak remediation evidence.', STY['td'])),
        (Paragraph('Negative external stakeholder context', STY['td_b']), Paragraph('Context driver (22%)', STY['td']),
         Paragraph('Relevant criticism, allegations, enforcement, litigation, NGO/union/regulator concerns or negative press linked to the same claim area.', STY['td'])),
        (Paragraph('Sector and channel sensitivity', STY['td_b']), Paragraph('Modifier (12%)', STY['td']),
         Paragraph('Consumer-facing communication, high-risk supply chains, fashion, food, retail, energy, chemicals, logistics or other sectors with elevated green/social claim exposure.', STY['td'])),
    ]
    flow.append(section_table(driver_rows, [W * 0.26, W * 0.20, W * 0.54]))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(
        'The calculation is <b>intentionally conservative</b>. A single isolated wording signal normally creates a '
        'limited or medium concern. High or very high scores require a stronger combination of severity, evidence '
        'gaps, regulatory relevance and/or retained negative external stakeholder signals.', STY['body']))
    flow.append(Spacer(1, 6))
    band_rows = [
        ('Score band', 'Interpretation'),
        (Paragraph('0 &ndash; 44  Low', ParagraphStyle('bl', parent=STY['td_b'], textColor=GREEN)),
         Paragraph('No material problematic claim retained or only limited wording risk visible.', STY['td'])),
        (Paragraph('45 &ndash; 74  Medium', ParagraphStyle('bm', parent=STY['td_b'], textColor=AMBER)),
         Paragraph('Some claim signals, wording risk or evidence gaps for review.', STY['td'])),
        (Paragraph('75 &ndash; 89  High', ParagraphStyle('bh', parent=STY['td_b'], textColor=DANGER)),
         Paragraph('Strong wording risk, evidence gaps and/or negative external stakeholder signals require priority review.', STY['td'])),
        (Paragraph('90 &ndash; 100  Very high', ParagraphStyle('bv', parent=STY['td_b'], textColor=colors.HexColor('#7a1e1e'))),
         Paragraph('Reserved for multiple severe claim signals with strong external or regulatory context.', STY['td'])),
    ]
    flow.append(section_table(band_rows, [W * 0.28, W * 0.72]))

    flow.append(Paragraph('6. External stakeholder signals', STY['h2']))
    flow.append(Spacer(1, 3))
    ext_rows = [
        ('Status', 'Meaning and score treatment'),
        (Paragraph('Candidate', STY['td_b']), Paragraph('Automatically discovered result that has not passed all entity, ownership, negative-polarity and relevance checks. Not displayed as a retained signal and no score impact.', STY['td'])),
        (Paragraph('Retained', STY['td_b']), Paragraph('Passed automated direct-entity, external-source, negative-content and green/social relevance checks. May affect entity context, but requires manual verification before external use.', STY['td'])),
        (Paragraph('Verified', STY['td_b']), Paragraph('Manually checked for source status, entity link, date and claim relevance. This is the strongest status available in the scan output.', STY['td'])),
        (Paragraph('Excluded', STY['td_b']), Paragraph('Company-owned evidence, positive or neutral news, competitor-primary articles, duplicates or results with insufficient entity/relevance evidence. No score impact.', STY['td'])),
    ]
    flow.append(section_table(ext_rows, [W * 0.22, W * 0.78]))

    flow.append(Paragraph('7. Coverage, confidence and source status', STY['h2']))
    coverage_rows=[
        ('Source status','Meaning'),
        (Paragraph('Retrieved and analysed',STY['td_b']),Paragraph('Usable text from the source entered the claim analysis.',STY['td'])),
        (Paragraph('Retrieved and partially analysed',STY['td_b']),Paragraph('Only part of the extracted text entered the bounded analysis text.',STY['td'])),
        (Paragraph('Limited text extracted',STY['td_b']),Paragraph('The page or document returned too little usable text for a complete assessment, often because of JavaScript rendering or extraction limits.',STY['td'])),
        (Paragraph('Retrieved but not analysed',STY['td_b']),Paragraph('The source was fetched but did not enter the final analysis because the crawl or text budget was reached.',STY['td'])),
        (Paragraph('Failed / skipped',STY['td_b']),Paragraph('The source could not be accessed, was a duplicate, was low relevance or was outside the crawl budget. It does not support findings.',STY['td'])),
    ]
    flow.append(section_table(coverage_rows,[W*.31,W*.69]))
    flow.append(Spacer(1,5))
    flow.append(Paragraph('Confidence reflects source coverage, extraction quality, access failures, fallback use, claim-level signals and whether external search was performed. It is reported separately from claim risk. A low detected risk with limited coverage must not be read as proof that risky claims are absent.',STY['body']))

    flow.append(Paragraph('8. Illustrative score example', STY['h2']))
    example_rows=[
        ('Illustrative input','Risk contribution'),
        (Paragraph('Generic consumer-facing environmental claim',STY['td_b']),Paragraph('Raises claim-wording severity; exact contribution depends on the retained pattern and channel.',STY['td'])),
        (Paragraph('Missing scope, methodology and verification',STY['td_b']),Paragraph('Raises evidence-gap risk.',STY['td'])),
        (Paragraph('Retained regulator investigation in the same claim area',STY['td_b']),Paragraph('Raises external-context risk; duplicate articles about the same incident should be treated as one incident.',STY['td'])),
        (Paragraph('High-sensitivity sector and consumer channel',STY['td_b']),Paragraph('Applies a bounded sector/channel modifier.',STY['td'])),
        (Paragraph('Result',STY['td_b']),Paragraph('The weighted components are capped at 100 and mapped to the published Low / Medium / High / Very high bands. The example is illustrative, not a fixed point schedule for every claim.',STY['td'])),
    ]
    flow.append(section_table(example_rows,[W*.38,W*.62]))
    flow.append(Spacer(1,5))
    flow.append(Paragraph(
        'Worked example (fully fictional, for illustration only): a claim scores 65/100 on claim-wording severity, '
        '70/100 on evidence-gap risk, 30/100 on external context and 40/100 on the sector/channel modifier. Applying '
        'the published weights above: 65&times;42% + 70&times;24% + 30&times;22% + 40&times;12% = 27.3 + 16.8 + 6.6 + '
        '4.8 = <b>56/100</b> (Medium risk band). This shows how the four weighted components combine into the final '
        'score; it does not disclose the full internal point schedule used to score any individual claim, which '
        'varies by claim type, channel and retained evidence.', STY['body']))

    flow.append(Paragraph('9. Limits of the scan', STY['h2']))
    flow.append(Paragraph(
        'The scan is a structured screening and prioritisation tool. It does not determine whether greenwashing or '
        'social washing legally occurred. Final assessment requires human review of the complete communication, '
        'applicable law, product context, evidence files, claim approval process, language versions and '
        'jurisdiction-specific enforcement practice.', STY['body']))
    flow.append(Spacer(1, 5))
    flow.append(Paragraph(
        'If a site blocks automated access or returns unusually little text on most pages checked, the report carries '
        'an explicit data-reliability warning. A low score under those conditions may reflect limited access to the '
        'site\'s content rather than a genuine absence of risky claims, and should be treated with caution.',
        STY['body']))
    flow.append(Spacer(1, 5))
    flow.append(Paragraph(
        'The tool is most useful before publication, campaign launch, website update, packaging change, sustainability '
        'report publication or supplier-claim reuse. It helps teams identify claim passages that should be specified, '
        'evidenced, reformulated or escalated.', STY['body']))
    flow.append(Spacer(1, 8))
    flow.append(Paragraph(
        '&copy; Durably - proprietary Sustainability Claims Risk Scan methodology. Indicative first-pass assessment only; results '
        'require legal, compliance and subject-matter review before external use.', STY['foot']))

    doc.build(flow, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


if __name__ == '__main__':
    pdf_bytes = build_methodology_pdf()
    open('methodology.pdf', 'wb').write(pdf_bytes)
    print('Generated', len(pdf_bytes), 'bytes')
