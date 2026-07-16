import app

# 1. Bare-name resolver must not accept a competitor domain.
orig_tavily,orig_google=app.tavily_search,app.google_search
app.tavily_search=lambda q,max_results=6:[
 {'title':'H&M official online store and fashion','url':'https://www2.hm.com','content':'H&M and other fast fashion brands including SHEIN'},
 {'title':'SHEIN official website','url':'https://www.shein.com','content':'Official SHEIN fashion website'},
]
app.google_search=lambda q,max_results=6:[]
try:
    url,note=app.resolve_company_website('SHEIN')
    assert 'shein.com' in url and 'hm.com' not in url,(url,note)
finally:
    app.tavily_search,app.google_search=orig_tavily,orig_google

# 2. Company inference is host-locked even when the page names competitors.
comp=app.infer_company('https://www.shein.com','Compare products from Zara, Inditex and H&M.')
assert comp['company']=='SHEIN',comp

# 3. H&M-primary article with an incidental SHEIN mention must be rejected.
hm_primary={
 'title':'H&M faces renewed greenwashing criticism',
 'url':'https://example-news.com/hm-greenwashing-case',
 'content':'The report concerns H&M. SHEIN is mentioned once as another fast-fashion company.'
}
assert not app.source_mentions_company(hm_primary,'SHEIN',['https://www.shein.com','https://www.sheingroup.com'])
assert app.entity_match_details(hm_primary,'SHEIN')['label'].startswith('Rejected')

# 4. Direct SHEIN regulator and NGO signals must be retained.
shein_reg={
 'title':'Italian authority fines SHEIN for misleading environmental claims',
 'url':'https://en.agcm.it/en/media/press-releases/2025/8/PS12709-shein',
 'content':'SHEIN was fined for misleading green claims and environmental messages.',
}
shein_ngo={
 'title':'Investigation finds illegal working hours at SHEIN suppliers',
 'url':'https://www.publiceye.ch/shein-working-conditions',
 'content':'The investigation found excessive working hours and low wages at SHEIN suppliers. SHEIN responded to the findings.',
}
assert app.source_mentions_company(shein_reg,'SHEIN')
assert app.is_green_negative_source(shein_reg)
assert app.source_mentions_company(shein_ngo,'SHEIN')
assert app.is_negative_external_source(shein_ngo)

# 5. Company-owned sources remain excluded.
owned={'title':'SHEIN Sustainability Report','url':'https://www.sheingroup.com/sustainability/report','content':'SHEIN sustainability progress.'}
assert app.is_company_owned_source(owned,'SHEIN',['https://www.shein.com','https://www.sheingroup.com'])

# 6. Internal claims are still detected from official corporate text.
company_text="At SHEIN, sustainability is integral to long-term resilience. We source responsible materials with a lower environmental impact. We are committed to fair working practices and responsible sourcing across our supply chain and human-rights programme."
green=app.detect_green_claims(company_text)
social=app.detect_claims(company_text)
assert any(x.get('dimension')=='green' for x in green),green
assert any(x.get('dimension')=='social' for x in social),social

# 7. End-to-end synthetic website scan: retain internal claims and only target-company external signals.
orig_crawl=app.crawl_with_related_sites
orig_ext=app.external
orig_extg=app.external_green
app.crawl_with_related_sites=lambda url,overall_deadline=None:(company_text,['https://www.shein.com','https://www.sheingroup.com/sustainability'],['Official corporate/group site also checked: https://www.sheingroup.com'],[{'url':'https://www.shein.com','ok':True,'thin':False}])
app.external=lambda company,findings=None,reviewed_pages=None:{'enabled':True,'results':[shein_ngo],'compact_sources':[],'search_diagnostics':{'raw_result_count':2,'company_matched_count':1,'negative_candidate_count':1,'retained_count':1,'fallback_used':False,'competitor_primary_rejected_count':1},'summary':'test'}
app.external_green=lambda company,findings=None,reviewed_pages=None:{'enabled':True,'results':[shein_reg],'compact_sources':[],'search_diagnostics':{'raw_result_count':2,'company_matched_count':1,'negative_candidate_count':1,'retained_count':1,'fallback_used':False,'competitor_primary_rejected_count':1},'summary':'test'}
try:
    result=app.analyse_url('https://www.shein.com')
    assert result['company']['company']=='SHEIN',result['company']
    assert len(result.get('green_findings',[]))>=1,result.get('green_findings')
    assert len(result.get('social_findings',[]))>=1,result.get('social_findings')
    ext=result.get('external_research',{})
    titles=' '.join(x.get('title','') for layer in ('green','social') for x in ext.get(layer,{}).get('targeted_negative_sources',[]))
    assert 'SHEIN' in titles.upper(),titles
    assert 'H&M' not in titles.upper(),titles
finally:
    app.crawl_with_related_sites=orig_crawl
    app.external=orig_ext
    app.external_green=orig_extg

print('V64 entity lock and internal-claims regression tests passed')

# 8. Generic resolver scoring must skip a competitor and choose a strong target-domain match.
orig_tavily,orig_google=app.tavily_search,app.google_search
app.tavily_search=lambda q,max_results=6:[
 {'title':'H&M official shop','url':'https://www2.hm.com','content':'H&M official store; Acme Fashion mentioned in a comparison.'},
 {'title':'Acme Fashion | Official Company Website','url':'https://www.acmefashion.com','content':'Official website of Acme Fashion.'},
]
app.google_search=lambda q,max_results=6:[]
try:
    url,note=app.resolve_company_website('Acme Fashion')
    assert 'acmefashion.com' in url and 'hm.com' not in url,(url,note)
finally:
    app.tavily_search,app.google_search=orig_tavily,orig_google

# 9. The actual related-site crawler must preserve budget and append corporate claims.
orig_crawl=app.crawl
calls=[]
def fake_crawl(url,max_extra_pages=None,deadline=None,log=None,candidate_source='primary'):
    calls.append((url,candidate_source))
    if 'sheingroup.com' in url:
        return company_text*2,['https://www.sheingroup.com','https://www.sheingroup.com/sustainability']
    return 'SHEIN fashion storefront and product catalogue.',['https://www.shein.com']
app.crawl=fake_crawl
try:
    text,pages,notes,log=app.crawl_with_related_sites('https://www.shein.com',overall_deadline=app.time.time()+20)
    assert any('sheingroup.com' in u for u,_ in calls),calls
    assert 'responsible materials' in text,text
    assert any('sheingroup.com' in p for p in pages),pages
    assert notes,notes
finally:
    app.crawl=orig_crawl

print('V64 extended resolver/corporate-site tests passed')
