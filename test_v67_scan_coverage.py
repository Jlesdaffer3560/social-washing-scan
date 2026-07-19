"""Regression tests for the transparent scan coverage/source register (v67)."""
import io
from pathlib import Path
import fitz
from pypdf import PdfReader
import app
import report_pdf

pages=[
    'https://example.com',
    'https://example.com/sustainability',
    'https://example.com/human-rights',
    'https://example.com/responsible-sourcing',
    'https://example.com/reports/sustainability-2025.pdf',
    'https://group.example.org/reports/modern-slavery.pdf',
]
documents=app.build_documents_checked(pages,{'audience':'Mixed / unclear','group':'mixed','empco_relevance':'Review','note':''},'')
log=[
    {'url':pages[0],'ok':True,'chars':1800,'method':'direct','source':'homepage','content_kind':'html'},
    {'url':pages[1],'ok':True,'chars':2400,'method':'direct','source':'linked','content_kind':'html'},
    {'url':pages[2],'ok':True,'chars':2200,'method':'reader_fallback','source':'sitemap','content_kind':'reader'},
    {'url':pages[3],'ok':True,'chars':2100,'method':'direct','source':'sitemap','content_kind':'html'},
    {'url':pages[4],'ok':True,'chars':15000,'method':'direct','source':'linked','content_kind':'pdf'},
    {'url':pages[5],'ok':True,'chars':12000,'method':'direct','source':'related_domain','content_kind':'pdf'},
    {'url':'https://example.com/esg','ok':False,'http_status':403,'error':'the website returned HTTP 403 (Forbidden).','method':'failed','source':'common_path'},
]
inv=app.build_scan_inventory(pages,documents,log)
assert inv['summary']['website_pages_reviewed']==4,inv
assert inv['summary']['documents_reviewed']==2,inv
assert inv['summary']['domains_reviewed']==2,inv
assert inv['summary']['fetch_failures']==1,inv
assert inv['summary']['fallback_pages']==1,inv
assert len(inv['website_pages'])==4
assert len(inv['documents'])==2
assert inv['failed_fetches'][0]['http_status']==403

sample={
    'company':{'company':'Example Group'},
    'source_label':'https://example.com',
    'original_url':'https://example.com',
    'analysis_date':'2026-07-16T12:00:00+00:00',
    'global_score':55,'global_risk':'Medium','green_score':62,'green_risk':'Medium','social_score':43,'social_risk':'Low',
    'entity_context_indicator':{'level':'Medium','note':'One external signal was retained.'},
    'claim_inventory':[
        {'claim_type':'Future environmental-performance claim','risk_level':'High','claim_score':90,'matched_phrase':'net zero by 2030','claim_text':'We will become net zero by 2030 across our operations.','why_flagged':'A future claim requires a public implementation plan and regular verification.','evidence_needed':['scope','baseline','milestones','resources','verification'],'suggested_rewrite':'Publish a detailed plan with scope, baseline, milestones, resources, progress and verification.','source_label':pages[1]},
        {'claim_type':'Supply-chain responsibility claim','risk_level':'High','claim_score':84,'matched_phrase':'responsible sourcing','claim_text':'Our responsible sourcing programme protects workers throughout the supply chain.','why_flagged':'The wording may imply broad supply-chain control.','evidence_needed':['supplier tiers','audit method','worker voice','remediation'],'suggested_rewrite':'State the covered supplier tiers, assessment method, findings, limitations and remediation.','source_label':pages[3]},
    ],
    'company_action_plan':[{'title':'Review claims','action':'Confirm wording and evidence.'},{'title':'Build evidence files','action':'Create a file per material claim.'},{'title':'Strengthen governance','action':'Introduce approval and review controls.'}],
    'report':{'pages_reviewed':pages},
    'scan_inventory':inv,
    'crawl_diagnostics':{'pages_attempted':7,'pages_failed':1,'pages_thin':0,'pages_retrieved_via_fallback':1,'detail':log},
    'confidence':{'level':'Medium','reasons':['six sources were reviewed','one page used a public text fallback','external search was active']},
    'external_research':{'green':{'targeted_negative_sources':[{'title':'Regulator reviews environmental claims','url':'https://news.example.net/example-review','source_name':'Public authority','published_date':'2026-06-01','status':'Investigation / regulatory review','review_status':'Retained - manual verification required','content':'The regulator is reviewing environmental claims made by Example Group.','related_claim_area':'Environmental claims','entity_match':'Direct'}]},'social':{'targeted_negative_sources':[]}},
}
pdf=report_pdf.build_company_report_pdf(sample)
reader=PdfReader(io.BytesIO(pdf))
assert len(reader.pages)==2,len(reader.pages)
text='\n'.join((p.extract_text() or '') for p in reader.pages)
assert 'ASSESSMENT COVERAGE' in text,text[-2000:]
assert 'REVIEWED PAGES AND DOCUMENTS' in text,text[-2000:]
assert '4 website page(s)' in text,text[-2000:]
assert '2 document(s) / PDF(s)' in text,text[-2000:]

# Geometric preflight: no words outside A4 page boxes.
doc=fitz.open(stream=pdf,filetype='pdf')
for page in doc:
    for word in page.get_text('words'):
        x0,y0,x1,y1,txt,*_=word
        assert x0>=-0.5 and x1<=page.rect.width+0.5,(page.number,txt,x0,x1)

frontend=Path('frontend.html').read_text(encoding='utf-8')
assert 'Scan coverage and reviewed sources' in frontend
assert 'downloadSourceRegisterCsv' not in frontend
assert 'The register distinguishes retrieval from actual analysis' not in frontend
assert 'renderCoverage(d)' in frontend

out=Path('PREVIEW_V67')
out.mkdir(exist_ok=True)
(out/'v67_scan_coverage_source_register_preview.pdf').write_bytes(pdf)
print('V67 scan coverage/source register tests passed')
