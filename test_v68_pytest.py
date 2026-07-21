from pathlib import Path
import app


def test_release_and_security_signature():
    assert app.APP_VERSION == 'hostable_v72_legal_basis_classification'
    payload={'company':{'company':'Example'},'global_score':50}
    app.attach_report_signature(payload)
    assert app.verify_report_signature(payload)
    payload['global_score']=90
    assert not app.verify_report_signature(payload)


def test_unverified_company_falls_back_to_flagged_guess(monkeypatch):
    """V72: a company with no known-site entry, no confident search match, and no
    reachable guessed domain must still resolve to *something* -- never raise -- so the
    scan can proceed. The returned note must clearly flag it as an unverified guess."""
    monkeypatch.setattr(app,'tavily_search',lambda *a,**k: [])
    monkeypatch.setattr(app,'google_search',lambda *a,**k: [])
    monkeypatch.setattr(app,'fetch_html',lambda *a,**k: (_ for _ in ()).throw(Exception('no such domain')))
    url,note=app.resolve_company_website('Fictional Unverified Holdings 8675309')
    assert url.startswith('https://www.')
    assert 'unverified' in note.lower() or 'could not be confidently verified' in note.lower()


def test_known_domain_guess_is_verified_via_live_content(monkeypatch):
    """V72: when a guessed domain is actually reachable and its content names the
    company, resolution must upgrade from an unverified guess to a verified match --
    this is what keeps bare-name scans working for companies without search-API
    coverage or without any search provider configured at all."""
    monkeypatch.setattr(app,'tavily_search',lambda *a,**k: [])
    monkeypatch.setattr(app,'google_search',lambda *a,**k: [])
    fake_html=('<html><head><title>Bakery Solutions | Puratos</title></head><body>'
               '<h1>Puratos</h1><p>Puratos is an international group which offers a full range of '
               'innovative food ingredients and services for the bakery, patisserie and chocolate '
               'sectors. Our headquarters are located in Belgium, where the company was founded in 1919. '
               'We serve artisans, retailers, industrial producers and food service operators in over '
               '100 countries around the world.</p></body></html>')
    monkeypatch.setattr(app,'fetch_html',lambda url,timeout=6: fake_html)
    url,note=app.resolve_company_website('Puratos')
    assert url=='https://www.puratos.com'
    assert 'verify the entity' in note.lower()
    assert 'unverified' not in note.lower()


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
