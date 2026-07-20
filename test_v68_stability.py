"""Regression tests for v68 stability, methodology, privacy and security changes."""
import io
from pathlib import Path
import fitz
from pypdf import PdfReader
import app
import report_pdf

assert app.APP_VERSION == 'hostable_v71_external_signal_recall_precision'
assert app.APP_RELEASE_LABEL == 'v71'

# Score bands and UI transparency must match backend bands.
frontend=Path('frontend.html').read_text(encoding='utf-8')
assert "if(n>=90)return 'Very high" in frontend
assert "if(n>=75)return 'High" in frontend
assert "if(n>=45)return 'Medium" in frontend
assert 'Document privacy:' in frontend
assert 'Analysis status' in frontend
assert 'characters analysed' in frontend.lower()
assert 'role="status" aria-live="polite"' in frontend
assert 'Build {{APP_RELEASE_LABEL}}' not in frontend
assert 'id="version"' not in frontend

# Bare-name resolution must not invent www.<name>.com when unverified.
old_tavily,old_google=app.tavily_search,app.google_search
app.tavily_search=lambda *a,**k: []
app.google_search=lambda *a,**k: []
try:
    try:
        app.resolve_company_website('Fictional Unverified Holdings 8675309')
        raise AssertionError('Unverified company names must require an exact URL')
    except ValueError as exc:
        assert 'exact official website URL' in str(exc)
finally:
    app.tavily_search,app.google_search=old_tavily,old_google

# Signed PDF payloads reject tampering.
payload={'company':{'company':'Example Group'},'global_score':55,'analysis_date':'2026-07-16T12:00:00+00:00'}
app.attach_report_signature(payload)
assert app.verify_report_signature(payload)
payload['global_score']=99
assert not app.verify_report_signature(payload)

pages=['https://example.com','https://example.com/sustainability','https://example.com/limited']
text=('Homepage text with no material claim.\n\nPAGE: https://example.com/sustainability\n'
      + 'Our sustainable product is supported by a roadmap and evidence. '*30
      + '\n\nPAGE: https://example.com/limited\nshort')
log=[
 {'url':pages[0],'ok':True,'chars':1200,'method':'direct','source':'homepage','content_kind':'html'},
 {'url':pages[1],'ok':True,'chars':2600,'method':'direct','source':'linked','content_kind':'html'},
 {'url':pages[2],'ok':True,'chars':80,'method':'direct_thin','source':'linked','content_kind':'html'},
]
docs=app.build_documents_checked(pages,{},text)
inv=app.build_scan_inventory(pages,docs,log,full_text=text)
statuses={x['url']:x['analysis_status'] for x in inv['website_pages']}
assert statuses[pages[1]] in {'Retrieved and analysed','Retrieved and partially analysed'}
assert statuses[pages[2]]=='Limited text extracted'
claims=[{'source_url':pages[1],'dimension':'green'},{'source_url':pages[1],'dimension':'social'}]
app.attach_claim_counts_to_inventory(inv,claims)
item=next(x for x in inv['website_pages'] if x['url']==pages[1])
assert item['claim_signal_count']==2
assert set(item['claim_dimensions'])=={'Green','Social'}

sample={
 'company':{'company':'Example Group'},'source_label':'https://example.com','original_url':'https://example.com',
 'analysis_date':'2026-07-16T12:00:00+00:00','global_score':55,'global_risk':'Medium','green_score':62,'green_risk':'Medium','social_score':43,'social_risk':'Low',
 'entity_context_indicator':{'level':'Medium','note':'One external signal was retained.'},
 'claim_inventory':[
  {'claim_type':'Future environmental-performance claim','risk_level':'High','claim_score':90,'matched_phrase':'net zero by 2030','claim_text':'We will become net zero by 2030 across our operations.','why_flagged':'A future claim requires a public implementation plan and regular verification.','evidence_needed':['scope','baseline','milestones','resources','verification'],'suggested_rewrite':'Publish a detailed plan with scope, baseline, milestones, resources, progress and verification.','source_label':pages[1]},
  {'claim_type':'Supply-chain responsibility claim','risk_level':'High','claim_score':84,'matched_phrase':'responsible sourcing','claim_text':'Our responsible sourcing programme protects workers throughout the supply chain.','why_flagged':'The wording may imply broad supply-chain control.','evidence_needed':['supplier tiers','audit method','worker voice','remediation'],'suggested_rewrite':'State covered supplier tiers, assessment method, findings, limitations and remediation.','source_label':pages[1]},
 ],
 'company_action_plan':[{'title':'Review claims','action':'Confirm wording and evidence.'},{'title':'Build evidence files','action':'Create a file per material claim.'},{'title':'Strengthen governance','action':'Introduce approval and review controls.'}],
 'report':{'pages_reviewed':pages},'scan_inventory':inv,
 'crawl_diagnostics':{'pages_attempted':3,'pages_failed':0,'pages_thin':1,'pages_retrieved_via_fallback':0,'detail':log},
 'confidence':{'level':'Medium','reasons':['three sources were reviewed','one page returned limited text','external search was active']},
 'external_research':{'green':{'targeted_negative_sources':[{'title':'Regulator reviews environmental claims','url':'https://news.example.net/example-review','source_name':'Public authority','published_date':'2026-06-01','status':'Investigation / regulatory review','review_status':'Retained - manual verification required','content':'The regulator is reviewing environmental claims made by Example Group.','related_claim_area':'Environmental claims','entity_match':'Direct','polarity':'negative'}]},'social':{'targeted_negative_sources':[]}},
}
pdf=report_pdf.build_company_report_pdf(sample)
assert len(PdfReader(io.BytesIO(pdf)).pages)==2
doc=fitz.open(stream=pdf,filetype='pdf')
for page in doc:
    for word in page.get_text('words'):
        x0,y0,x1,y1,txt,*_=word
        assert x0>=-0.5 and x1<=page.rect.width+0.5,(page.number,txt,x0,x1)

method=PdfReader('methodology.pdf')
assert len(method.pages)==3
method_text='\n'.join((p.extract_text() or '') for p in method.pages)
assert 'Main forced-labour and supply-chain assurance lens' in method_text
assert 'dominant driver' not in method_text.lower()
assert 'Coverage, confidence and source status' in method_text
assert 'Candidate' in method_text and 'Verified' in method_text

out=Path('PREVIEW_V68'); out.mkdir(exist_ok=True)
(out/'v68_stability_and_source_status_preview.pdf').write_bytes(pdf)
print('V68 stability, methodology, privacy and security tests passed')
