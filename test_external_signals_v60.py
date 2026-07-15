import importlib.util
from pathlib import Path

APP=Path(__file__).with_name('app.py')
spec=importlib.util.spec_from_file_location('durably_app_v60',APP)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

RESULTS=[
 {'title':'Investigation launched against Shein for possible misleading environmental claims','url':'https://en.agcm.it/en/media/press-releases/2024/9/PS12709','content':'The Italian Competition Authority opened an investigation into possible misleading environmental claims by Shein.','score':0.95,'provider':'Tavily'},
 {'title':'Italian regulator hits Shein with greenwashing fine','url':'https://www.reuters.com/sustainability/shein-greenwashing-fine','content':'The authority fined Shein for misleading environmental claims.','score':0.9,'provider':'Tavily'},
 {'title':'SHEIN, ultra-fast fashion and forced labour','url':'https://www.business-humanrights.org/documents/40793/2024_Shein_briefing.pdf','content':'A civil society briefing raises forced labour and human rights concerns involving Shein supply chains.','score':0.88,'provider':'Google Custom Search'},
 {'title':'The fast fashion model: why the problem goes beyond Shein','url':'https://www.antislavery.org/latest/shein-fast-fashion-problem/','content':'Anti-Slavery International discusses forced labour scrutiny and worker conditions in Shein supply chains.','score':0.85,'provider':'Tavily'},
 {'title':'Sustainability at SHEIN','url':'https://www.sheingroup.com/sustainability','content':'Our sustainability strategy and annual report.','score':0.99,'provider':'Tavily'},
 {'title':'Shein wins sustainability innovation award','url':'https://example.com/shein-award','content':'A positive award and partnership announcement with no criticism.','score':0.8,'provider':'Tavily'},
 {'title':'External analysis criticises Shein sustainability report','url':'https://www.esgdive.com/news/shein-greenwashing-complaint-italy-fast-fashion/','content':'The article discusses Shein sustainability report figures and a regulator greenwashing investigation.','score':0.84,'provider':'Tavily'},
]

green=mod.targeted_negative_sources(RESULTS,'Shein',5,['https://www.sheingroup.com'],mod.is_green_negative_source)
social=mod.targeted_negative_sources(RESULTS,'Shein',5,['https://www.sheingroup.com'],mod.is_negative_external_source)

gurls={x['url'] for x in green}; surls={x['url'] for x in social}
assert any('agcm.it' in u for u in gurls), green
assert any('reuters.com' in u or 'esgdive.com' in u for u in gurls), green
assert not any('sheingroup.com' in u for u in gurls), green
assert any('business-humanrights.org' in u for u in surls), social
assert any('antislavery.org' in u for u in surls), social
assert not any('sheingroup.com' in u for u in surls), social
# Regression: an external article mentioning a sustainability report must not be treated as company-owned.
ext_article=RESULTS[-1]
assert not mod.is_company_owned_source(ext_article,'Shein',['https://www.sheingroup.com'])
assert mod.is_company_owned_source(RESULTS[4],'Shein',['https://www.sheingroup.com'])
assert mod.APP_VERSION=='hostable_v60_external_signal_recall_precision'
print('green retained',len(green),[x['category'] for x in green])
print('social retained',len(social),[x['category'] for x in social])
print('V60 external-signal tests passed')

# Query orchestration regression: generic searches must run even when claim-specific findings are sparse.
mod.TAVILY_API_KEY='test-key'
def fake_search(query,max_results=6):
    # Return a different fixture depending on the query family.
    if 'greenwashing' in query or 'environmental claims' in query or 'sustainability claims' in query:
        return RESULTS[:2]+[RESULTS[-1]],[{'provider':'Mock','status':'ok','results':3}]
    if 'forced labour' in query or 'labour rights' in query or 'human rights' in query:
        return RESULTS[2:4],[{'provider':'Mock','status':'ok','results':2}]
    return [],[{'provider':'Mock','status':'ok','results':0}]
mod.search_public_sources=fake_search
ge=mod.external_green('Shein',[])
se=mod.external('Shein',[])
assert ge['enabled'] and len(ge['results'])>=2, ge
assert se['enabled'] and len(se['results'])>=2, se
assert len(ge.get('queries_run',[]))>=4
assert len(se.get('queries_run',[]))>=4
print('query orchestration passed',len(ge['results']),len(se['results']))
