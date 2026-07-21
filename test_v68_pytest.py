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
    def fake_open(url,timeout=8,accept=None,max_bytes=None):
        if 'puratos.com' in url:
            return fake_html.encode(),'text/html',url
        raise Exception('not found')
    monkeypatch.setattr(app,'_open_public_url',fake_open)
    url,note=app.resolve_company_website('Puratos')
    assert url=='https://www.puratos.com'
    assert 'verify the entity' in note.lower()
    assert 'unverified' not in note.lower()


def test_flagship_domain_preferred_over_country_domain(monkeypatch):
    """V72.1: when a company's regional/country domain (e.g. .be) and its flagship
    global domain (.com) both validate, resolution must prefer the flagship domain --
    otherwise a bare-name scan can land on a thinner regional storefront instead of the
    main corporate site, where the fuller sustainability/ESG content usually lives."""
    monkeypatch.setattr(app,'tavily_search',lambda *a,**k: [])
    monkeypatch.setattr(app,'google_search',lambda *a,**k: [])
    com_html=('<html><head><title>Bakery Solutions | Puratos</title></head><body>'
              '<h1>Puratos</h1><p>Puratos is an international group offering bakery, patisserie and '
              'chocolate ingredients worldwide, serving customers in over 100 countries. Global '
              'headquarters located in Belgium since 1919. News, sustainability report, careers.</p>'
              '</body></html>')
    be_html=('<html><head><title>Puratos Belux</title></head><body>'
             '<h1>Puratos Belgium</h1><p>Puratos Belux is the local Belgian office of the '
             'international Puratos group, offering the full range of products and solutions for '
             'the bakery, patisserie and chocolate sector. Contact our local team for more '
             'information about our products and services in Belgium.</p></body></html>')
    def fake_open(url,timeout=8,accept=None,max_bytes=None):
        if 'puratos.com' in url:
            return com_html.encode(),'text/html',url
        if 'puratos.be' in url:
            return be_html.encode(),'text/html',url
        raise Exception('not found')
    monkeypatch.setattr(app,'_open_public_url',fake_open)
    url,note=app.resolve_company_website('Puratos')
    assert url=='https://www.puratos.com'
    # If .com happens to be unreachable, .be must still be used rather than blocking or
    # falling back to an unverified guess.
    def fake_open_only_be(url,timeout=8,accept=None,max_bytes=None):
        if 'puratos.com' in url:
            raise Exception('blocked')
        if 'puratos.be' in url:
            return be_html.encode(),'text/html',url
        raise Exception('not found')
    monkeypatch.setattr(app,'_open_public_url',fake_open_only_be)
    url,note=app.resolve_company_website('Puratos')
    assert url=='https://www.puratos.be'
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
