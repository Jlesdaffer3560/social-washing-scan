"""Generic entity-lock and PDF-boundary regression tests for v65."""
import io
import json
from pathlib import Path
from pypdf import PdfReader
import app
import report_pdf

# Generic bare-name resolution must choose the target, not a competitor.
orig_tavily, orig_google = app.tavily_search, app.google_search
app.tavily_search = lambda q, max_results=6: [
    {'title':'Rival Retail official website','url':'https://www.rivalretail.com','content':'Rival Retail; Acme Fashion mentioned once.'},
    {'title':'Acme Fashion | Official company website','url':'https://www.acmefashion.com','content':'Official corporate website of Acme Fashion.'},
]
app.google_search = lambda q, max_results=6: []
try:
    url, note = app.resolve_company_website('Acme Fashion')
    assert 'acmefashion.com' in url and 'rivalretail.com' not in url, (url, note)
finally:
    app.tavily_search, app.google_search = orig_tavily, orig_google

# Host/input identity is generic and cannot be replaced by competitor mentions.
company = app.infer_company('https://www.acmefashion.com', 'Comparison with Rival Retail and Other Brand.', 'Acme Fashion')
assert company['company'] == 'Acme Fashion', company

# Incidental external mention is rejected for any company.
incidental = {
    'title':'Rival Retail faces greenwashing investigation',
    'url':'https://news.example/rival-greenwashing',
    'content':'This case concerns Rival Retail. Acme Fashion is mentioned once as a competitor.'
}
assert not app.source_mentions_company(incidental, 'Acme Fashion', ['https://www.acmefashion.com'])
assert app.entity_match_details(incidental, 'Acme Fashion', ['https://www.acmefashion.com'])['label'].startswith('Rejected')

# Body-only sources are allowed only with strong, prominent, repeated direct evidence.
direct_body = {
    'title':'Authority publishes apparel enforcement update',
    'url':'https://authority.example.gov/enforcement/update',
    'content':'Acme Fashion is under investigation for misleading environmental claims. The authority says Acme Fashion used unsupported carbon-neutral wording. Acme Fashion may respond before a final decision.'
}
assert app.source_mentions_company(direct_body, 'Acme Fashion', ['https://www.acmefashion.com'])

# Exact official domains are owned; watchdog domains containing the brand substring are not.
owned = {'url':'https://www.acmefashion.com/sustainability','title':'Acme Fashion report','content':''}
watchdog = {'url':'https://www.acmefashionwatch.org/report','title':'Acme Fashion Watch report','content':'NGO criticism of Acme Fashion labour practices.'}
assert app.is_company_owned_source(owned, 'Acme Fashion', ['https://www.acmefashion.com'])
assert not app.is_company_owned_source(watchdog, 'Acme Fashion', ['https://www.acmefashion.com'])

# Generic related official-site discovery.
orig_run, orig_key = app._v60_run_queries, app.TAVILY_API_KEY
app.TAVILY_API_KEY = 'test-key'
app._v60_run_queries = lambda queries: ([
    {'title':'Acme Fashion Group - Official sustainability reporting','url':'https://www.acmegroup.com/sustainability','content':'Official corporate sustainability reporting for Acme Fashion. Acme Fashion Group publishes its annual impact report.'},
    {'title':'News analysis of Acme Fashion','url':'https://news.example/acme','content':'Media coverage of Acme Fashion.'},
], [], {'Mock'}, list(queries))
try:
    related = app._v65_discover_related_official_sites('Acme Fashion', 'https://www.acmefashion.com', limit=2)
    assert any('acmegroup.com' in x for x in related), related
    assert all('news.example' not in x for x in related), related
finally:
    app._v60_run_queries = orig_run
    app.TAVILY_API_KEY = orig_key

# PDF layout: risk labels, including 'Very high', must remain within the page and card.
sample = {
    'company': {'company':'Acme Fashion'},
    'source_label':'https://www.acmefashion.com',
    'original_url':'https://www.acmefashion.com',
    'analysis_date':'2026-07-16T12:00:00+00:00',
    'global_score':88,'global_risk':'High','green_score':92,'green_risk':'Very high','social_score':80,'social_risk':'High',
    'entity_context_indicator': {'level':'High','note':'Two relevant external signals were retained.'},
    'claim_inventory':[
        {'claim_type':'Future environmental-performance claim with a deliberately long heading to test wrapping','risk_level':'Very high','claim_score':95,'matched_phrase':'net zero by 2030','claim_text':'Acme Fashion will be net zero by 2030 through a comprehensive transition programme.','why_flagged':'The future claim requires a public, measurable and verifiable implementation plan.','evidence_needed':['scope','baseline','milestones','resources','verification','limitations'],'suggested_rewrite':'Publish measurable milestones, resources, governance, verification and limitations.','source_label':'Sustainability report'},
        {'claim_type':'Absolute or purity environmental wording','risk_level':'High','claim_score':90,'matched_phrase':'zero waste','claim_text':'All operations are zero waste.','why_flagged':'Absolute wording creates a high evidence burden.','evidence_needed':['scope','methodology','reporting period'],'suggested_rewrite':'Qualify the scope and disclose the method and limitations.','source_label':'Corporate website'},
        {'claim_type':'Generic environmental claim','risk_level':'High','claim_score':86,'matched_phrase':'more sustainable','claim_text':'Our products are more sustainable.','why_flagged':'The environmental attribute and baseline are unclear.','evidence_needed':['attribute','baseline','method'],'suggested_rewrite':'Specify the exact attribute, baseline and evidence.','source_label':'Product page'},
    ],
    'company_action_plan':[{'title':'Review claims','action':'Review all consumer-facing claims.'},{'title':'Build evidence files','action':'Create claim-specific files.'},{'title':'Implement governance','action':'Add approval controls.'}],
    'report': {'pages_reviewed':['https://www.acmefashion.com','https://www.acmefashion.com/sustainability','https://www.acmegroup.com/report']},
    'confidence': {'level':'Medium','reasons':['several company pages were reviewed','external public-source search was active','claim-level signals were detected']},
    'external_research': {'green': {'targeted_negative_sources':[{'title':'Authority investigates Acme Fashion environmental claims','url':'https://authority.example.gov/acme','source_name':'authority.example.gov','published_date':'2026-06-01','status':'Investigation / regulatory review','review_status':'Retained - manual verification required','content':'The authority opened an investigation into environmental claims.','related_claim_area':'Environmental claims','entity_match':'Direct - target in title'}]}, 'social': {'targeted_negative_sources':[]}},
}
pdf = report_pdf.build_company_report_pdf(sample)
reader = PdfReader(io.BytesIO(pdf))
assert len(reader.pages) == 2
text = '\n'.join(page.extract_text() or '' for page in reader.pages)
assert 'Very high' in text and 'Future environmental-performance' in text

# Word coordinates must remain within page bounds.
try:
    import fitz
    doc = fitz.open(stream=pdf, filetype='pdf')
    for page in doc:
        width = page.rect.width
        for word in page.get_text('words'):
            x0,y0,x1,y1,txt,*_ = word
            assert x0 >= -0.5 and x1 <= width + 0.5, (page.number, txt, x0, x1, width)
except ImportError:
    pass

out = Path('PREVIEW_V65')
out.mkdir(exist_ok=True)
(out/'v65_generic_entity_and_layout_preview.pdf').write_bytes(pdf)
print('V65 generic entity-lock and PDF-boundary tests passed')
