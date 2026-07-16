from pathlib import Path
import app


def test_release_and_security_signature():
    assert app.APP_VERSION == 'hostable_v69_report_token_strict_negative_external_signals'
    payload={'company':{'company':'Example'},'global_score':50}
    app.attach_report_signature(payload)
    assert app.verify_report_signature(payload)
    payload['global_score']=90
    assert not app.verify_report_signature(payload)


def test_unverified_company_requires_exact_url(monkeypatch):
    monkeypatch.setattr(app,'tavily_search',lambda *a,**k: [])
    monkeypatch.setattr(app,'google_search',lambda *a,**k: [])
    try:
        app.resolve_company_website('Fictional Unverified Holdings 8675309')
    except ValueError as exc:
        assert 'exact official website URL' in str(exc)
    else:
        raise AssertionError('Unverified bare company names must not create an invented domain')


def test_frontend_score_bands_and_privacy():
    text=Path('frontend.html').read_text(encoding='utf-8')
    assert "if(n>=90)return 'Very high" in text
    assert "if(n>=75)return 'High" in text
    assert "if(n>=45)return 'Medium" in text
    assert 'Document privacy:' in text
    assert 'Analysis status' in text


def test_inventory_distinguishes_limited_text():
    pages=['https://example.com','https://example.com/limited']
    text='Homepage content.\n\nPAGE: https://example.com/limited\nshort'
    log=[
        {'url':pages[0],'ok':True,'chars':900,'method':'direct','source':'homepage','content_kind':'html'},
        {'url':pages[1],'ok':True,'chars':50,'method':'direct_thin','source':'linked','content_kind':'html'},
    ]
    docs=app.build_documents_checked(pages,{},text)
    inv=app.build_scan_inventory(pages,docs,log,full_text=text)
    limited=next(x for x in inv['website_pages'] if x['url']==pages[1])
    assert limited['analysis_status']=='Limited text extracted'
