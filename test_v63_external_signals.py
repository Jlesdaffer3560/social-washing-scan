import app

AGCM = {
    'title': 'Italian Competition Authority: 1 million euros fine imposed on Shein for misleading and omissive green claims',
    'url': 'https://en.agcm.it/en/media/press-releases/2025/8/PS12709',
    'content': 'The Italian Competition Authority imposed a fine on the company responsible for managing Shein websites in Europe for misleading environmental messages and green claims.',
    'provider': 'Google Custom Search',
}
PUBLIC_EYE = {
    'title': "Interviews with factory employees refute Shein's promises to make improvements",
    'url': 'https://www.publiceye.ch/en/topics/fashion/interviews-with-factory-employees-refute-sheins-promises-to-make-improvements',
    'content': 'A follow-up investigation found illegal working hours and piecework wages remain typical at Shein suppliers.',
    'provider': 'Tavily',
}
CLW = {
    'title': "Fast Fashion, Slow Justice: Labor Conditions in Shein's Supply Workshops",
    'url': 'https://chinalaborwatch.org/fast-fashion-slow-justice-labor-conditions-in-sheins-supply-workshops-kangle-village-guangzhou/',
    'content': 'A new investigation reveals labor rights risks, low wages and excessive overtime for workers in Shein supply workshops.',
    'provider': 'Tavily',
}
OWNED = {
    'title': 'SHEIN Sustainability and Social Impact Report',
    'url': 'https://www.sheingroup.com/sustainability/report',
    'content': 'SHEIN reports progress in sustainability and fair working practices.',
}
POSITIVE = {
    'title': 'Shein expands sustainability programme',
    'url': 'https://example-news.com/shein-expands-sustainability-programme',
    'content': 'Shein announces a partnership and new sustainable collection.',
}
WATCHDOG = {
    'title': 'Shein Watch reports labour concerns',
    'url': 'https://sheinwatch.org/report',
    'content': 'An NGO report alleges excessive working hours and low wages at Shein suppliers.',
}

assert app.source_mentions_company(AGCM, 'SHEIN Group')
assert app.is_green_negative_source(AGCM)
assert not app.is_negative_external_source(AGCM)

assert app.is_negative_external_source(PUBLIC_EYE)
assert not app.is_green_negative_source(PUBLIC_EYE)
assert app.is_negative_external_source(CLW)

assert app.is_company_owned_source(OWNED, 'SHEIN Group', ['https://www.sheingroup.com'])
assert not app.is_company_owned_source(WATCHDOG, 'SHEIN Group', ['https://www.sheingroup.com'])
assert not app.is_green_negative_source(POSITIVE)
assert not app.is_negative_external_source(POSITIVE)

# Test fallback: primary queries return nothing; stakeholder-domain queries return AGCM.
original = app._v60_run_queries

def fake_run(queries):
    if any('site:agcm.it' in q for q in queries):
        return [AGCM], [{'provider':'Mock','status':'ok','results':1}], {'Mock'}, list(queries)
    return [], [{'provider':'Mock','status':'ok','results':0}], {'Mock'}, list(queries)

app._v60_run_queries = fake_run
try:
    ranked, raw, attempts, providers, queries, diag = app._v63_search_dimension('SHEIN Group', [], 'green')
    assert len(ranked) == 1
    assert diag['fallback_used'] is True
    assert diag['retained_count'] == 1
    assert diag['company_matched_count'] == 1
finally:
    app._v60_run_queries = original

# Targeted output should keep external stakeholder signals and exclude the company site.
kept = app.targeted_negative_sources([PUBLIC_EYE, CLW, OWNED, POSITIVE], 'SHEIN Group', 5, ['https://www.sheingroup.com'], app.is_negative_external_source)
assert len(kept) == 2, kept
assert all('sheingroup.com' not in x.get('url','') for x in kept)

print('V63 external signal tests passed')
