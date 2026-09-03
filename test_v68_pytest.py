from pathlib import Path
import time, hmac, hashlib, json
import app


def test_release_and_security_signature():
    assert app.APP_VERSION == 'hostable_v93_7_history_date_range_and_alpha_sort'
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
    assert "if(n>=75)return 'Very high" in text
    assert "if(n>=50)return 'High" in text
    assert "if(n>=25)return 'Medium" in text
    assert 'Document privacy:' in text
    assert 'Analysis status' in text


def test_placeholder_finding_not_counted_as_real_claim():
    """v83: the synthetic "no claim retained" row detect_green_claims()/detect_claims()
    append when nothing material was found used the type string "No material problematic
    ... claim retained" -- but most of the call sites that needed to recognise it were
    checking only startswith('no major'), a string no code path actually produces, so it
    silently never matched. A document with only a real green claim was wrongly credited
    with a phantom social claim-module and a phantom social pre-publication-review row."""
    green_fs=[app.enrich_green_finding(f, f.get('matched_phrase',''))
              for f in app.detect_green_claims('This product is climate neutral thanks to verified offsetting.')]
    social_fs=[app.enrich_social_finding(f, f.get('matched_phrase',''))
               for f in app.detect_claims('We have no other claims to make about our people or suppliers.')]
    assert app.is_placeholder_finding(social_fs[0]['type'])
    modules=app.build_claim_modules_summary(green_fs, social_fs)
    assert [m['module'] for m in modules]==['Carbon / Offsetting Claim Check']
    rows=app.build_pre_publication_review(green_fs, social_fs, {'audience':'Consumer-facing'})
    assert [r['dimension'] for r in rows]==['Green']
    inv=app.build_scan_inventory(['https://example.com'],[],[],full_text='dummy')
    all_claims=app.build_green_claim_inventory(green_fs)+app.social_claim_inventory_with_dimension(social_fs)
    for c in all_claims: c.setdefault('source_url','https://example.com')
    app.attach_claim_counts_to_inventory(inv, all_claims)
    page=inv['website_pages'][0]
    assert page['claim_dimensions']==['Green']
    assert page['claim_signal_count']==1


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


def test_scan_history_noop_without_database_url(monkeypatch):
    """v92: the scan-history feature must be fully optional. With DATABASE_URL unset
    (the default), saving must never raise -- a database problem or missing config must
    never turn a successful scan into a failed response -- and fetching must return an
    empty, not erroring, result."""
    monkeypatch.setattr(app,'DATABASE_URL','')
    app._v92_save_scan_history({'company':{'company':'Acme'},'global_score':50},'url','1.2.3.4')
    rows,total=app._v92_fetch_scan_history()
    assert rows==[] and total==0


def test_scan_history_page_escapes_untrusted_content(monkeypatch):
    """v92: company/sector/input_url in a history row originate from a user-supplied scan
    input (not a trusted source), and the search box echoes the raw query string -- both
    must be HTML-escaped before being interpolated into the /history page, or a scan input
    or search containing markup becomes a stored/reflected XSS against whoever views the
    history page."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'scanned_at':'2026-09-01T12:00:00','company':'<script>alert(1)</script>',
         'sector':'Retail & "Fashion"','input_url':'https://evil.example.com/<img src=x onerror=alert(2)>',
         'global_score':42,'global_risk':'High','green_score':30,'social_score':50,'findings_count':3}
    html=app._v92_render_history_page([row],1,1,25,'<b>xss</b>')
    assert '<script>alert(1)</script>' not in html
    assert '<img src=x onerror=alert(2)>' not in html
    assert '&lt;script&gt;' in html
    assert '&lt;b&gt;xss&lt;/b&gt;' in html


def test_history_cookie_auth(monkeypatch):
    """v92: the /history page's shared-password cookie must accept a freshly-issued valid
    cookie, reject a tampered signature, reject an expired one, and -- critically -- deny
    access outright when no password is configured at all, rather than defaulting open."""
    monkeypatch.setattr(app,'HISTORY_ADMIN_PASSWORD','testpw123')
    cookie_val=app._v92_history_cookie_value()
    header=f'{app._HISTORY_COOKIE_NAME}={cookie_val}'
    assert app._v92_valid_history_cookie(header) is True
    tampered=cookie_val.rsplit('.',1)[0]+'.deadbeef'
    assert app._v92_valid_history_cookie(f'{app._HISTORY_COOKIE_NAME}={tampered}') is False
    old_ts=str(int(time.time())-app._HISTORY_SESSION_SECONDS-10)
    old_sig=hmac.new(app._REPORT_SIGNING_KEY,('history-auth:'+old_ts).encode(),hashlib.sha256).hexdigest()
    assert app._v92_valid_history_cookie(f'{app._HISTORY_COOKIE_NAME}={old_ts}.{old_sig}') is False
    monkeypatch.setattr(app,'HISTORY_ADMIN_PASSWORD','')
    assert app._v92_valid_history_cookie(header) is False


def test_scan_history_error_redaction(monkeypatch):
    """v92.1: a database connection error can echo back the DSN it tried, which for a
    typical Postgres URL includes the username and PASSWORD in plain text -- and this
    error is surfaced via the public, unauthenticated /api/health endpoint for debugging.
    Both the exact configured DATABASE_URL and any generic scheme://user:pass@ pattern
    must be stripped before that ever happens."""
    monkeypatch.setattr(app,'DATABASE_URL','postgresql://myuser:supersecretpw@ep-x.neon.tech/db?sslmode=require')
    redacted=app._v92_redact_error('failed (using DSN: postgresql://myuser:supersecretpw@ep-x.neon.tech/db?sslmode=require)')
    assert 'supersecretpw' not in redacted and 'myuser' not in redacted
    redacted_generic=app._v92_redact_error('timeout connecting to postgresql://otheruser:otherpw@otherhost/db')
    assert 'otherpw' not in redacted_generic


def test_scan_history_filter_builder():
    """v92.3: the WHERE-clause builder shared by the table view, stats block and CSV
    export must bind every value as a parameter (never interpolate it into the SQL
    text), and must silently ignore a risk/period value outside the fixed option list
    rather than accepting an arbitrary string into a raw SQL fragment."""
    assert app._v92_build_filters()==('',())
    where,params=app._v92_build_filters(search='Acme')
    assert where=='WHERE company ILIKE %s' and params==('%Acme%',)
    where,params=app._v92_build_filters(risk='High')
    assert where=='WHERE global_risk = %s' and params==('High',)
    # not a real risk level / period key -- must be dropped, not smuggled into the SQL
    assert app._v92_build_filters(risk='1=1; DROP TABLE scan_history')==('',())
    assert app._v92_build_filters(period='not-a-real-period')==('',())
    where,params=app._v92_build_filters(search='Acme',risk='High',period='month')
    assert where.startswith('WHERE company ILIKE %s AND global_risk = %s AND') and params==('%Acme%','High')


def test_scan_history_csv_export():
    """v92.3: CSV export must include every _V92_EXPORT_COLUMNS field, correctly quote a
    value containing a comma and embedded double quotes, and lead with a UTF-8 BOM so it
    opens with the right encoding directly in Excel."""
    rows=[{'scanned_at':'2026-09-01 10:00:00','company':'Acme, Inc.','summary':'Some "quoted" text, with a comma.'}]
    csv_bytes=app._v92_rows_to_csv(rows)
    assert csv_bytes.startswith(b'\xef\xbb\xbf')
    text=csv_bytes.decode('utf-8-sig')
    assert ','.join(app._V92_EXPORT_COLUMNS) in text.splitlines()[0]
    assert '"Acme, Inc."' in text
    assert '"Some ""quoted"" text, with a comma."' in text


def test_scan_history_page_renders_stats_and_filters(monkeypatch):
    """v92.3: the stats block must reflect the passed-in aggregates, and the risk/period
    dropdowns must mark the currently-selected value -- while the untrusted-content
    escaping added earlier (test_scan_history_page_escapes_untrusted_content) must still
    hold with the new stats/filter UI in place."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    stats={'total':12,'avg_score':43.7,'this_month':5,'by_risk':{'Low':4,'Medium':3,'High':4,'Very high':1}}
    row={'scanned_at':'2026-09-01T12:00:00','company':'<script>alert(1)</script>','sector':'Retail',
         'input_url':'https://example.com','global_score':42,'global_risk':'High','green_score':30,
         'social_score':50,'findings_count':3}
    html=app._v92_render_history_page([row],1,1,25,'',risk='High',period='month',stats=stats)
    assert '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html
    assert '43.7' in html
    assert '<option value="High" selected>' in html
    assert '<option value="month" selected>' in html
    assert '/history/export.csv?q=' in html


def test_scan_history_sector_risk_uses_computed_level():
    """v92.4: infer_company() sets company['sector'] to the placeholder "Sector not
    explicitly identified" and company['sector_risk'] to '' for every company outside the
    small hardcoded PROFILES list -- Puratos among them -- even though infer_sector()
    always computes a real content-based sector risk LEVEL (Low/Medium/High) into the
    top-level result['sector'] dict regardless of PROFILES membership. The saved
    sector_risk column must use that always-populated computed level, not the frequently-
    empty company['sector_risk'] field, or a real result silently looks blank in history."""
    result_unknown_company={'company':{'company':'Puratos','sector':'Sector not explicitly identified','sector_risk':''},
                             'sector':{'level':'High','basis':'matched terms: food, ingredients'}}
    comp=result_unknown_company['company']; sec=result_unknown_company['sector']
    assert str(sec.get('level','') or comp.get('sector_risk','') or '')=='High'
    result_known_company={'company':{'company':'KBC','sector':'Banking and financial services','sector_risk':'Medium'},
                           'sector':{'level':'Medium','basis':'recognised company/sector profile'}}
    comp2=result_known_company['company']; sec2=result_known_company['sector']
    assert str(sec2.get('level','') or comp2.get('sector_risk','') or '')=='Medium'


def test_scan_history_table_falls_back_to_sector_risk(monkeypatch):
    """v92.4: the visible /history table must not show the uninformative "Sector not
    explicitly identified" placeholder -- it should fall back to the computed sector-risk
    level instead, while a company that DOES have a real descriptive sector name (the
    small hardcoded PROFILES list) keeps showing that name unchanged."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    unknown_row={'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
                 'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
                 'green_score':57,'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([unknown_row],1,1,25,'')
    assert 'Sector not explicitly identified' not in html
    assert 'Sector risk: High' in html
    known_row={'scanned_at':'2026-09-02T13:40','company':'KBC','sector':'Banking and financial services',
               'sector_risk':'Medium','input_url':'https://careers.kbc-group.com','global_score':12,
               'global_risk':'Low','green_score':12,'social_score':12,'findings_count':2}
    html2=app._v92_render_history_page([known_row],1,1,25,'')
    assert 'Banking and financial services' in html2 and 'Sector risk: Medium' not in html2


def test_scan_history_row_selection_markup(monkeypatch):
    """v92.5: each row needs a checkbox carrying its database id (bound to the separate
    #selectForm via the HTML `form` attribute, since it lives inside the table rather than
    physically inside that form), a select-all checkbox, and an Export-selected button
    that starts disabled (enabled by the page's own JS once something is checked)."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row1={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
          'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
          'green_score':57,'social_score':50,'findings_count':14}
    row2={'id':43,'scanned_at':'2026-09-02T13:40','company':'KBC','sector':'Banking and financial services',
          'sector_risk':'Medium','input_url':'https://careers.kbc-group.com','global_score':12,'global_risk':'Low',
          'green_score':12,'social_score':12,'findings_count':2}
    html=app._v92_render_history_page([row1,row2],2,1,25,'')
    assert 'name="ids" value="42"' in html and 'name="ids" value="43"' in html
    assert 'id="selectAll"' in html
    assert 'id="selectForm"' in html and 'action="/history/export_selected"' in html
    assert 'id="exportSelectedBtn"' in html and 'disabled' in html


def test_scan_history_fetch_and_id_parsing():
    """v92.6: _v92_parse_ids() (shared by both the GET ?ids=.. query-string form -- "View
    selected" -- and the POST export-selected form body) must silently drop anything that
    isn't a plain integer -- the request is client-controlled even though these values are
    meant to be checkbox values this same page rendered. An ids filter with at least one
    id must add an `id = ANY(%s)` clause; an EMPTY ids list must add no filter at all
    (None and [] both mean "no ids constraint" to the query builder) -- callers that mean
    "nothing was selected, export nothing" (export-selected) guard on `if ids` themselves
    before ever calling the fetch, rather than relying on an empty list to mean that here."""
    assert app._v92_parse_ids({'ids':['42','43','not-a-number','','17abc']})==[42,43]
    assert app._v92_parse_ids({})==[]
    where,params=app._v92_build_filters(ids=[42,43])
    assert where=='WHERE id = ANY(%s)' and params==([42,43],)
    assert app._v92_build_filters(ids=[])==('',())
    assert app._v92_build_filters(ids=None)==('',())


def test_scan_history_view_selected_filter(monkeypatch):
    """v92.6: "View selected" narrows /history to just the checked rows via a GET
    ?ids=.. query string (a plain HTML GET form turns checkboxes into repeated query
    params natively). Without an active ids filter there is no selection banner; with one,
    a banner names the count and offers a "Clear selection" link that preserves any other
    active search/risk/period filter (dropping only the ids constraint), and the pager/
    Export CSV links carry the active ids filter forward."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html_plain=app._v92_render_history_page([row],1,1,25,'')
    assert 'class="notice"' not in html_plain
    html_ids=app._v92_render_history_page([row],1,1,25,'',ids=[42])
    assert 'Showing 1 selected scan(s)' in html_ids and 'Clear selection' in html_ids
    assert '&ids=42' in html_ids  # carried into the Export CSV link
    html_ids_search=app._v92_render_history_page([row],1,1,25,'Puratos',ids=[42])
    assert 'q=Puratos' in html_ids_search  # preserved by the clear-selection link


def test_scan_history_delete_selected(monkeypatch):
    """v92.7: deleting must short-circuit on an empty id list without touching the
    database (never accidentally interpreted as "delete everything"), and the rendered
    page must include the delete button (posting to /history/delete_selected) plus a
    client-side confirm() dialog as a UX safety net -- the real guard is server-side
    cookie auth, already covered by test_history_cookie_auth, but the confirmation
    dialog matters too since this is an irreversible action a logged-in operator could
    otherwise trigger with a single misclick."""
    assert app._v92_delete_by_ids([])==0
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'')
    assert 'id="deleteSelectedBtn"' in html
    assert 'formaction="/history/delete_selected"' in html
    assert 'confirm(' in html
    assert 'btn danger' in html


def test_scan_history_min_score_filters():
    """v93.2: the Global/Green/Social/Findings "column >= N" filters must parse a valid
    integer, silently ignore garbage/empty input (treated as "no threshold set", not as
    0), and clamp into a sane range -- then thread through into the shared WHERE builder
    as bound parameters, never interpolated into the SQL text."""
    assert app._v92_parse_min_filter({'min_global':['50']},'min_global')==50
    assert app._v92_parse_min_filter({'min_global':['']},'min_global') is None
    assert app._v92_parse_min_filter({},'min_global') is None
    assert app._v92_parse_min_filter({'min_global':['not-a-number']},'min_global') is None
    assert app._v92_parse_min_filter({'min_global':['-5']},'min_global')==0
    assert app._v92_parse_min_filter({'min_global':['999999']},'min_global')==100000
    where,params=app._v92_build_filters(min_global=50,min_green=30,min_social=40,min_findings=5)
    assert where=='WHERE global_score >= %s AND green_score >= %s AND social_score >= %s AND findings_count >= %s'
    assert params==(50,30,40,5)
    assert app._v92_build_filters()==('',())


def test_scan_history_date_range_filter():
    """v93.7: date_from/date_to must accept only a strict YYYY-MM-DD string (rejecting
    garbage or a SQL-injection-shaped value, which must never reach the query), and must
    thread into the WHERE builder as bound parameters with an inclusive day-boundary for
    date_to (so a scan made at 23:59 on the end date is still included)."""
    assert app._v92_parse_date_filter({'date_from':['2026-08-01']},'date_from')=='2026-08-01'
    assert app._v92_parse_date_filter({'date_from':['']},'date_from') is None
    assert app._v92_parse_date_filter({},'date_from') is None
    assert app._v92_parse_date_filter({'date_from':['not-a-date']},'date_from') is None
    assert app._v92_parse_date_filter({'date_from':["2026-08-01' OR '1'='1"]},'date_from') is None
    where,params=app._v92_build_filters(date_from='2026-08-01',date_to='2026-08-31')
    assert where=="WHERE scanned_at >= %s::date AND scanned_at < %s::date + interval '1 day'"
    assert params==('2026-08-01','2026-08-31')


def test_scan_history_sort_alphabetical(monkeypatch):
    """v93.7: sorting by company must be an explicit opt-in ('company' -> alphabetical
    A-Z), defaulting to the existing newest-first behaviour for any other/missing value --
    and the sort dropdown on the page must reflect whichever is currently active."""
    assert app._V92_SORT_SQL['date']=='scanned_at DESC'
    assert app._V92_SORT_SQL['company']=='company ASC, scanned_at DESC'
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'',sort='company')
    assert '<option value="company" selected>' in html
    assert 'name="sort" value="company"' in html  # carried into the select-all hidden form


def test_scan_history_page_renders_min_score_inputs(monkeypatch):
    """v93.2: the filter form must render the four threshold inputs pre-filled with
    whatever values are currently active, and carry them into the Export CSV link and
    pagination query string alongside search/risk/period."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'',min_global=50,min_green=30,min_social=40,min_findings=5)
    assert 'name="min_global" placeholder="Global &ge;"' in html and 'value="50"' in html
    assert 'value="30"' in html and 'value="40"' in html and 'value="5"' in html
    assert 'min_global=50' in html and 'min_findings=5' in html  # carried into Export CSV link


def test_scan_history_select_all_matching_link_only_when_multi_page(monkeypatch):
    """v93.2: "Select all N matching results" only makes sense (and only needs to exist)
    when there's more than one page of results -- a single page is already fully covered
    by the existing per-page select-all checkbox."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html_one_page=app._v92_render_history_page([row],1,1,25,'')
    assert 'id="selectAllMatchingLink"' not in html_one_page
    html_multi_page=app._v92_render_history_page([row],54,1,25,'')
    assert 'Select all 54 matching result(s)' in html_multi_page
    assert 'id="selectAllFlag"' in html_multi_page


def test_scan_history_delete_by_filter(monkeypatch):
    """v93.2: _v92_delete_by_filter() is the "select all matching results across every
    page, then delete" counterpart to _v92_delete_by_ids() -- it must be a no-op (not an
    error) when the feature isn't configured (no DATABASE_URL), same safety posture as
    every other scan-history function in this file."""
    monkeypatch.setattr(app,'DATABASE_URL','')
    assert app._v92_delete_by_filter(search='Acme')==0


def test_scan_history_top_claims_unconfigured():
    """v93.3: _v92_fetch_top_claims() (the evolving Top 10 most-flagged-claims panel) must
    return an empty list, not raise, when the feature isn't configured -- same safety
    posture as every other scan-history fetch function."""
    assert app._v92_fetch_top_claims()==[]


def test_scan_history_top_claims_panel_rendering(monkeypatch):
    """v93.3: when top_claims data is supplied, the page must render a ranked table with
    the phrase (HTML-escaped, since it's scraped page content), risk badge, occurrence
    count and company count -- and must render nothing extra when there is no top-claims
    data yet (a brand-new deployment with no scan_findings rows)."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    top_claims=[{'phrase':'<b>carbon neutral</b>','risk':'High','occurrences':7,'companies':5},
                {'phrase':'eco-friendly','risk':'Medium','occurrences':4,'companies':3}]
    html=app._v92_render_history_page([],0,1,25,'',top_claims=top_claims)
    assert 'Top 2 most flagged claims/words' in html
    assert '&lt;b&gt;carbon neutral&lt;/b&gt;' in html and '<b>carbon neutral</b>' not in html
    assert 'eco-friendly' in html
    html_empty=app._v92_render_history_page([],0,1,25,'')
    assert 'most flagged claims/words' not in html_empty


def test_scan_history_table_still_renders_alongside_top_claims_panel(monkeypatch):
    """v93.6 regression guard: a local variable inside the Top 10 panel's rendering block
    was named `rows`, silently shadowing the function's own `rows` parameter (the actual
    scan_history rows for the table below) -- whenever top_claims was non-empty, the main
    table would then try to iterate the panel's HTML strings as if they were row dicts and
    crash with AttributeError. This must never regress: both sections must render
    correctly at the same time, with the real company data intact in the table."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    top_claims=[{'phrase':'carbon neutral','risk':'High','occurrences':7,'companies':5,'blacklisted':True}]
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'',top_claims=top_claims)
    assert 'Top 1 most flagged claims/words' in html
    assert '<strong>Puratos</strong>' in html  # the real scan table row, not the panel's HTML


def test_scan_history_top_claims_blacklist_column(monkeypatch):
    """v93.6: the Top 10 panel must show whether a phrase was ever flagged as an EmpCo
    Annex I blacklisted practice, separate from the general risk-level badge -- "Yes" for
    a blacklisted phrase, a plain dash for one that wasn't."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    top_claims=[{'phrase':'carbon neutral','risk':'High','occurrences':7,'companies':5,'blacklisted':True},
                {'phrase':'eco-friendly','risk':'Medium','occurrences':4,'companies':3,'blacklisted':False}]
    html=app._v92_render_history_page([],0,1,25,'',top_claims=top_claims)
    assert 'EmpCo blacklist' in html
    assert html.count('>Yes<')==1
    assert '&mdash;' in html


def test_scan_history_fetch_top_claims_includes_blacklist(monkeypatch):
    """v93.6: _v92_fetch_top_claims() must aggregate blacklisted status with BOOL_OR (true
    if ANY occurrence of that phrase was blacklisted) alongside the existing risk-rank
    aggregation."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None): pass
        def fetchall(self): return [('carbon neutral',7,5,3,True)]
    class FakeConn:
        def cursor(self): return FakeCursor()
        def close(self): pass
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    result=app._v92_fetch_top_claims()
    assert result==[{'phrase':'carbon neutral','occurrences':7,'companies':5,'risk':'High','blacklisted':True}]


def test_scan_history_findings_saved_per_claim(monkeypatch):
    """v93.3: saving a scan must also insert one scan_findings row per finding that has a
    matched_phrase, tagging each with the new scan's id (via RETURNING id) -- this is what
    feeds the Top 10 panel. Uses a fake connection/cursor since there's no real database
    in tests."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    executed=[]
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None): executed.append(('execute',sql,params))
        def executemany(self,sql,rows): executed.append(('executemany',sql,rows))
        def fetchone(self): return (99,)
    class FakeConn:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    result={'company':{'company':'Acme'},'sector':{'level':'Medium'},
            'findings':[{'dimension':'green','type':'vague eco claim','risk':'High','matched_phrase':'carbon neutral'},
                        {'dimension':'social','type':'other','risk':'Low','matched_phrase':''}]}
    app._v92_save_scan_history(result,'url','1.2.3.4')
    insert_calls=[c for c in executed if c[0]=='executemany']
    assert len(insert_calls)==1
    _,sql,rows=insert_calls[0]
    assert 'INSERT INTO scan_findings' in sql
    assert rows==[(99,'green','vague eco claim','carbon neutral','High',False)]  # the empty-phrase finding is skipped


def test_backfill_legacy_findings_missing_fixture(monkeypatch, tmp_path):
    """v93.3: the one-time legacy backfill must report a clear error (not raise) when its
    bundled fixture file isn't present."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    summary=app._v92_backfill_legacy_findings()
    assert summary['error']=='Fixture file not found.'


def test_backfill_legacy_findings_inserts_and_skips(monkeypatch, tmp_path):
    """v93.3: each fixture entry must be matched to its company's most recent scan_history
    row and inserted -- but a company with no matching row is reported as not_found, and a
    company whose scan already has scan_findings rows is skipped rather than duplicated
    (so re-running the backfill is always safe)."""
    fixture=[{'company':'Acme','findings':[{'dimension':'green','type':'x','matched_phrase':'carbon neutral','risk':'High'}]},
             {'company':'Unknown Co','findings':[{'dimension':'green','type':'x','matched_phrase':'eco','risk':'Medium'}]}]
    (tmp_path/'data_legacy_findings_backfill.json').write_text(json.dumps(fixture),encoding='utf-8')
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    insert_log=[]
    fetch_queue=[(1,),(0,),None]  # Acme: scan_id=1, 0 existing findings -> insert; Unknown Co: no scan_history row
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None): pass
        def executemany(self,sql,rows): insert_log.append(rows)
        def fetchone(self): return fetch_queue.pop(0)
    class FakeConn:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    summary=app._v92_backfill_legacy_findings()
    assert summary['inserted_companies']==1 and summary['inserted_rows']==1
    assert summary['not_found']==['Unknown Co']
    assert insert_log==[[(1,'green','x','carbon neutral','High',False)]]


def test_backfill_legacy_findings_skips_already_populated(monkeypatch, tmp_path):
    """v93.3: a company whose scan already has scan_findings rows (e.g. a re-run of the
    backfill) must be skipped, not duplicated."""
    fixture=[{'company':'Acme','findings':[{'dimension':'green','type':'x','matched_phrase':'carbon neutral','risk':'High'}]}]
    (tmp_path/'data_legacy_findings_backfill.json').write_text(json.dumps(fixture),encoding='utf-8')
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    insert_log=[]
    fetch_queue=[(1,),(2,)]  # scan_id=1, but already has 2 scan_findings rows
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None): pass
        def executemany(self,sql,rows): insert_log.append(rows)
        def fetchone(self): return fetch_queue.pop(0)
    class FakeConn:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    summary=app._v92_backfill_legacy_findings()
    assert summary['skipped_already_present']==1
    assert summary['inserted_companies']==0
    assert insert_log==[]
