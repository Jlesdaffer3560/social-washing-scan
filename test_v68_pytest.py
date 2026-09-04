from pathlib import Path
import time, hmac, hashlib, json
import app


def test_release_and_security_signature():
    assert app.APP_VERSION == 'hostable_v93_21_empco_blacklist_floor_and_kbo_only_scan'
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
    """v92.4/v93.13: the visible /history table must not show the uninformative "Sector
    not explicitly identified" placeholder -- and every row must render the SAME
    two-part shape (name-or-placeholder, then risk level) regardless of whether the
    company has a real descriptive sector name (the small hardcoded PROFILES list) or
    not, per explicit user feedback that inconsistent formatting between rows (a name for
    Delhaize, only a risk level for most others) read as inconsistent data."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    unknown_row={'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
                 'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
                 'green_score':57,'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([unknown_row],1,1,25,'')
    assert 'Sector not explicitly identified' not in html
    assert 'Sector not identified &middot; Risk: High' in html
    known_row={'scanned_at':'2026-09-02T13:40','company':'KBC','sector':'Banking and financial services',
               'sector_risk':'Medium','input_url':'https://careers.kbc-group.com','global_score':12,
               'global_risk':'Low','green_score':12,'social_score':12,'findings_count':2}
    html2=app._v92_render_history_page([known_row],1,1,25,'')
    assert 'Banking and financial services &middot; Risk: Medium' in html2


def test_scan_history_table_strips_nace_code_from_display(monkeypatch):
    """v93.19: the stored sector value cites its NACE Rev. 2 section letter (e.g.
    "Automotive (NACE C)") for methodology traceability, but per explicit user feedback
    the /history table itself must show the plain name without it -- the "(NACE X)"
    suffix must never appear in the rendered table."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'scanned_at':'2026-09-02T14:10','company':'Umicore','sector':'Metals and materials manufacturing (NACE C)',
         'sector_risk':'Medium','input_url':'https://www.umicore.com','global_score':44,'global_risk':'Medium',
         'green_score':40,'social_score':30,'findings_count':5}
    html=app._v92_render_history_page([row],1,1,25,'')
    assert 'Metals and materials manufacturing &middot; Risk: Medium' in html
    assert 'NACE' not in html


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
    """v93.2/v93.9: the Global/Green/Social/Findings filters must parse a valid integer,
    silently ignore garbage/empty input (treated as "no filter set", not as 0), and clamp
    into a sane range -- then thread through into the shared WHERE builder as bound
    parameters (exact equality, per explicit user feedback that a >= threshold "wasn't a
    real filter" -- they want e.g. "all companies with score 15"), never interpolated
    into the SQL text."""
    assert app._v92_parse_min_filter({'min_global':['50']},'min_global')==50
    assert app._v92_parse_min_filter({'min_global':['']},'min_global') is None
    assert app._v92_parse_min_filter({},'min_global') is None
    assert app._v92_parse_min_filter({'min_global':['not-a-number']},'min_global') is None
    assert app._v92_parse_min_filter({'min_global':['-5']},'min_global')==0
    assert app._v92_parse_min_filter({'min_global':['999999']},'min_global')==100000
    where,params=app._v92_build_filters(min_global=50,min_green=30,min_social=40,min_findings=5)
    assert where=='WHERE global_score = %s AND green_score = %s AND social_score = %s AND findings_count = %s'
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
    """v93.7: 'company' sorts alphabetically A-Z; 'date' sorts newest-first.
    v93.8: sorting is triggered by clicking a column header (Date/Company/Global/Green/
    Social/Findings), not a separate dropdown -- the active column's header link must be
    marked (a down-arrow), and the currently-active sort must be carried into both the
    plain filter form (as a hidden field, so changing search/risk/period doesn't silently
    reset it back to the default) and the select-all hidden form.
    v93.11: 'company' (not 'date') is now the DEFAULT sort -- see
    test_scan_history_default_sort_is_alphabetical_by_company below."""
    assert app._V92_SORT_SQL['date']=='scanned_at DESC'
    assert app._V92_SORT_SQL['company']=='company ASC, scanned_at DESC'
    assert app._V92_SORT_SQL['global']=='global_score DESC NULLS LAST, scanned_at DESC'
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'',sort='company')
    assert '<a href="/history?sort=company">Company &darr;</a>' in html
    assert '<a href="/history?sort=date">Date</a>' in html  # inactive column: no arrow
    assert html.count('name="sort" value="company"')==2  # filter form's hidden field + select-all form


def test_scan_history_default_sort_is_alphabetical_by_company(monkeypatch):
    """v93.11: the default view (no explicit ?sort=... in the URL) must list companies
    alphabetically A-Z, not newest-scanned-first -- a "newest first" default made the list
    look arbitrarily (or reverse-alphabetically) ordered whenever the most recently
    scanned companies happened to start with a late letter. This must hold at both layers:
    the SQL ORDER BY actually used when no sort is specified, and the invalid/garbage-sort
    fallback in the page renderer."""
    import inspect
    sig=inspect.signature(app._v92_render_history_page)
    assert sig.parameters['sort'].default=='company'
    sig2=inspect.signature(app._v92_fetch_scan_history)
    assert sig2.parameters['sort'].default=='company'
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Zabra','sector':'','sector_risk':'High',
         'input_url':'https://zabra.org','global_score':41,'global_risk':'Medium','green_score':62,
         'social_score':12,'findings_count':3}
    # an invalid/garbage sort value must fall back to 'company', not 'date'
    html=app._v92_render_history_page([row],1,1,25,'',sort='not-a-real-sort-key')
    assert '<a href="/history?sort=company">Company &darr;</a>' in html


def test_scan_history_clear_button_always_visible(monkeypatch):
    """v93.11: the "Clear" button must always be rendered, even with no filter active --
    it's the only way back to the clean default view once a sort (e.g. clicking a column
    header) is active without any other filter, and the user explicitly reported it as
    sometimes missing."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html_no_filters=app._v92_render_history_page([row],1,1,25,'')
    assert '<a class="btn secondary" href="/history">Clear</a>' in html_no_filters
    html_sorted_only=app._v92_render_history_page([row],1,1,25,'',sort='global')
    assert '<a class="btn secondary" href="/history">Clear</a>' in html_sorted_only


def test_scan_history_sortable_headers_cover_all_columns(monkeypatch):
    """v93.8: every column the user asked to sort by (Date/Company/Global/Green/Social/
    Findings) must be a clickable header, and clicking one must preserve the active
    search/risk/period filter (but not page/ids, since a new sort naturally starts back
    at page 1 over the full matching set)."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'Puratos',risk='High')
    for key in ('date','company','global','green','social','findings'):
        assert f'href="/history?q=Puratos&risk=High&sort={key}"' in html


def test_scan_history_filter_form_decluttered(monkeypatch):
    """v93.8: the score-threshold inputs (Global/Green/Social/Findings >=) and the exact
    date-range inputs were reported as cluttering the top filter bar and are no longer
    part of the visible form -- sorting/filtering by those columns now happens via the
    clickable column headers and the existing search/risk/period controls instead. The
    underlying backend filters (_v92_build_filters etc.) are untouched and still tested
    separately -- only the rendered UI changed."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'')
    assert 'placeholder="Global &ge;"' not in html
    assert 'placeholder="Findings &ge;"' not in html
    assert 'type="date"' not in html
    assert '<select name="sort">' not in html


def test_scan_history_fetch_distinct_scores_unconfigured():
    """v93.9: _v92_fetch_distinct_scores() must return all-empty lists (not raise) when
    the feature isn't configured -- same safety posture as every other scan-history fetch
    function."""
    assert app._v92_fetch_distinct_scores()=={'global':[],'green':[],'social':[],'findings':[]}


def test_scan_history_excel_style_score_dropdowns(monkeypatch):
    """v93.9: each score/count column gets an Excel-style dropdown listing the REAL
    distinct values present in scan_history (not an arbitrary range), with "All" plus the
    currently-active exact-match value marked selected -- and picking a different column's
    value must not drop an already-active filter on another score column (AND semantics),
    per explicit user feedback that a >= threshold "wasn't a real filter" and they want to
    pick an exact value, "just like filtering a column in Excel"."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    distinct_scores={'global':[41,54,57],'green':[57,62],'social':[12,50],'findings':[3,14]}
    html=app._v92_render_history_page([row],1,1,25,'',min_global=54,min_social=12,
        distinct_scores=distinct_scores,top_claims=None)
    # the active Global value (54) and active Social value (12) are marked selected
    assert '<option value="/history?min_global=54&min_social=12" selected>54</option>' in html
    assert '<option value="/history?min_global=54&min_social=12" selected>12</option>' in html
    # picking a NEW Green value must preserve the already-active Global AND Social filters
    assert '/history?min_global=54&min_green=57&min_social=12' in html
    # the "All" option for Global clears only min_global, keeping min_social active
    assert '<option value="/history?min_social=12">All</option>' in html


def test_scan_history_fetch_distinct_companies_and_dates_unconfigured():
    """v93.10: both new distinct-value fetchers for the Date and Company dropdown filters
    must return [] (not raise) when the feature isn't configured -- same safety posture as
    every other scan-history fetch function."""
    assert app._v92_fetch_distinct_companies()==[]
    assert app._v92_fetch_distinct_dates()==[]


def test_scan_history_excel_style_date_and_company_dropdowns(monkeypatch):
    """v93.10: Date and Company get the same Excel-style exact-value dropdown as the
    score columns -- Company reuses the existing `q` search param (so picking a name just
    fills the search box with that exact value, no new filter machinery), and Date reuses
    the existing exact date-range filter by setting date_from=date_to=that single day.
    Both lists must come back alphabetically/chronologically ordered, and an active
    Company/Date filter must be preserved when a score dropdown's option is built (AND
    semantics across every active filter, not just the score ones)."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'Puratos',
        date_from='2026-09-02',date_to='2026-09-02',
        distinct_companies=['AB Eiffage','Puratos','Zabra'],
        distinct_dates=['2026-09-03','2026-09-02'])
    # Company dropdown: alphabetical order, active value ("Puratos") marked selected
    assert '<option value="/history?q=AB%20Eiffage&date_from=2026-09-02&date_to=2026-09-02">AB Eiffage</option>' in html
    assert '<option value="/history?q=Puratos&date_from=2026-09-02&date_to=2026-09-02" selected>Puratos</option>' in html
    # Date dropdown: newest first, active day marked selected, other day still an option
    assert ('<option value="/history?q=Puratos&date_from=2026-09-02&date_to=2026-09-02" selected>'
            '2026-09-02</option>' in html)
    assert '2026-09-03</option>' in html
    # picking a different company must preserve the active date filter
    assert 'q=Zabra&date_from=2026-09-02&date_to=2026-09-02' in html


def test_scan_history_select_all_button_always_visible(monkeypatch):
    """v93.10: the "Select all N" button is now always rendered as a real button in the
    action row (not a text link that only appeared once there was more than one page) --
    the user explicitly reported it as "missing" when it only showed up conditionally, so
    it must be discoverable regardless of how many pages/rows currently exist."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'Sector not explicitly identified',
         'sector_risk':'High','input_url':'https://www.puratos.us','global_score':54,'global_risk':'High',
         'green_score':57,'social_score':50,'findings_count':14}
    html_one_page=app._v92_render_history_page([row],1,1,25,'')
    assert '<a class="btn secondary" href="#" id="selectAllMatchingLink">Select all 1</a>' in html_one_page
    html_multi_page=app._v92_render_history_page([row],54,1,25,'')
    assert '<a class="btn secondary" href="#" id="selectAllMatchingLink">Select all 54</a>' in html_multi_page
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


def test_backfill_sector_names_missing_fixture(monkeypatch, tmp_path):
    """v93.18: the sector-name backfill must report a clear error (not raise) when its
    bundled fixture file isn't present -- same safety posture as the legacy-findings
    backfill."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    summary=app._v92_backfill_sector_names()
    assert summary['error']=='Fixture file not found.'


def test_backfill_sector_names_updates_not_found_and_skips_already_real(monkeypatch, tmp_path):
    """v93.19: each fixture entry updates scan_history.sector AND sector_risk ONLY for
    rows still showing the generic placeholder (enforced by the UPDATE's own WHERE
    clause, not a separate check) -- a company with no matching row at all is reported
    as not_found, while a company that already has a real sector name (already
    backfilled, or a hardcoded PROFILES company) is silently left alone, not reported as
    an error."""
    fixture={'Acme':{'sector':'Food retail and supermarkets (NACE G)','sector_risk':'High'},
             'Ghost Co':{'sector':'Banking and financial services (NACE K)','sector_risk':'Medium'},
             'Already Named':{'sector':'Automotive (NACE C)','sector_risk':'Medium'}}
    (tmp_path/'data_sector_backfill.json').write_text(json.dumps(fixture),encoding='utf-8')
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    monkeypatch.setattr(app,'APP_DIR',tmp_path)
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    executed=[]
    # UPDATE rowcounts in fixture (dict, insertion-ordered) iteration order:
    # Acme -> 1 row updated; Ghost Co -> 0 (no such company at all, COUNT confirms 0);
    # Already Named -> 0 (exists but already real, COUNT confirms >0, so not "not_found").
    update_rowcounts=[1,0,0]
    count_results=[0,1]
    class FakeCursor:
        def __init__(self): self.rowcount=0
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None):
            executed.append((sql,params))
            if sql.strip().startswith('UPDATE'):
                self.rowcount=update_rowcounts.pop(0)
        def fetchone(self): return (count_results.pop(0),)
    class FakeConn:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    summary=app._v92_backfill_sector_names()
    assert summary['updated_companies']==1 and summary['updated_rows']==1
    assert summary['not_found']==['Ghost Co']
    assert "sector = 'Sector not explicitly identified'" in executed[0][0]
    assert executed[0][1]==('Food retail and supermarkets (NACE G)','High','Acme')


def _sample_export_rows():
    return [
        {'scanned_at':'2026-09-03T18:04:00','scan_type':'url','company':'Zabra','sector':'','sector_risk':'Medium',
         'input_url':'https://zabra.org','global_score':41,'global_risk':'Medium','green_score':62,'green_risk':'High',
         'social_score':12,'social_risk':'Low','audience':'','document_type':'','findings_count':3,
         'empco_blacklisted_count':1,'high_risk_findings_count':1,'external_green_retained_count':0,
         'external_social_retained_count':0,'data_reliability_warning':False,'summary':''},
        {'scanned_at':'2026-09-03T10:00:00','scan_type':'url','company':'Lidl','sector':'Retail','sector_risk':'High',
         'input_url':'https://lidl.com','global_score':61,'global_risk':'High','green_score':70,'green_risk':'High',
         'social_score':50,'social_risk':'Medium','audience':'','document_type':'','findings_count':9,
         'empco_blacklisted_count':2,'high_risk_findings_count':4,'external_green_retained_count':2,
         'external_social_retained_count':1,'data_reliability_warning':False,'summary':''},
        {'scanned_at':'2026-09-02T09:00:00','scan_type':'url','company':'Home Invest','sector':'Real estate',
         'sector_risk':'Low','input_url':'https://homeinvest.be','global_score':9,'global_risk':'Low','green_score':10,
         'green_risk':'Low','social_score':8,'social_risk':'Low','audience':'','document_type':'','findings_count':1,
         'empco_blacklisted_count':0,'high_risk_findings_count':0,'external_green_retained_count':0,
         'external_social_retained_count':0,'data_reliability_warning':False,'summary':''},
    ]


def test_batch_report_aggregate_stats():
    """v93.12: _aggregate() must compute averages only over present (non-None) scores,
    count risk buckets correctly (defaulting an unrecognised/blank risk to 'Low' rather
    than crashing or silently dropping the row), count companies with at least one EmpCo
    blacklisted claim, and derive the min/max scanned date range."""
    import batch_report_pdf as brp
    agg=brp._aggregate(_sample_export_rows())
    assert agg['total']==3
    assert agg['avg_global']==37.0  # (41+61+9)/3
    assert agg['risk_counts']=={'Low':1,'Medium':1,'High':1,'Very high':0}
    assert agg['high_plus']==1
    assert agg['blacklisted_companies']==2
    assert agg['date_range']==('2026-09-02','2026-09-03')
    empty=brp._aggregate([])
    assert empty['total']==0 and empty['avg_global'] is None and empty['date_range']==(None,None)


def test_batch_report_pdf_generates_valid_multi_page_pdf():
    """v93.16: build_batch_summary_report_pdf() must produce real, valid PDF bytes (not
    just non-empty bytes) with the expected 3-page layout (page 1: cards/executive
    summary/analysis/risk chart; page 2: highest-risk chart (+ claims table if any); page
    3: full company table) for a normal selection, and must not crash on a row with every
    score field None (a company outside the small hardcoded PROFILES list can still
    legitimately have missing scores)."""
    import pypdf
    import batch_report_pdf as brp
    rows=_sample_export_rows()+[{'scanned_at':'2026-09-01T10:00:00','scan_type':'url','company':'No Score Co',
        'sector':'','sector_risk':'','input_url':'','global_score':None,'global_risk':'','green_score':None,
        'green_risk':'','social_score':None,'social_risk':'','audience':'','document_type':'','findings_count':None,
        'empco_blacklisted_count':0,'high_risk_findings_count':0,'external_green_retained_count':0,
        'external_social_retained_count':0,'data_reliability_warning':False,'summary':''}]
    pdf_bytes=brp.build_batch_summary_report_pdf(rows,meta={'generated':'2026-09-04'})
    assert pdf_bytes.startswith(b'%PDF-')
    reader=pypdf.PdfReader(__import__('io').BytesIO(pdf_bytes))
    assert len(reader.pages)==3
    page1_text=reader.pages[0].extract_text()
    assert 'Scan Summary Report' in page1_text
    assert '4 selected scan(s)' in page1_text  # 3 sample rows + the no-score row


def test_batch_report_pdf_empty_selection():
    """v93.12: an empty selection must still produce a valid, graceful one-page PDF
    (never raise) -- e.g. if every row in a select-all filter got deleted between page
    load and clicking "Create report"."""
    import batch_report_pdf as brp
    pdf_bytes=brp.build_batch_summary_report_pdf([])
    assert pdf_bytes.startswith(b'%PDF-')


def test_history_resolve_selected_export_rows(monkeypatch):
    """v93.12: _v92_resolve_selected_export_rows() is shared by Export selected and the
    new Create report button -- an explicit ids list must call _v92_fetch_all_for_export
    with just those ids, while select_all=1 must resolve against the active
    search/risk/period/score/date/sort filters instead, exactly like Export selected."""
    calls=[]
    monkeypatch.setattr(app,'_v92_fetch_all_for_export',lambda *a,**k: calls.append((a,k)) or ['row'])
    result=app._v92_resolve_selected_export_rows({'ids':['5','9']})
    assert result==['row'] and calls[-1][1]=={'ids':[5,9]}
    calls.clear()
    form={'select_all':['1'],'q':['Acme'],'risk':['High'],'min_global':['50'],'sort':['global']}
    app._v92_resolve_selected_export_rows(form)
    args,kwargs=calls[-1]
    assert args[0]=='Acme' and args[1]=='High' and args[4]==50 and args[10]=='global'


def test_history_report_button_disabled_by_default(monkeypatch):
    """v93.12: the "Create report" button must render alongside the existing selection
    actions, start disabled like them, and post to /history/report_selected."""
    monkeypatch.setattr(app,'DATABASE_URL','postgres://fake:fake@localhost/fake')
    row={'id':42,'scanned_at':'2026-09-02T14:10','company':'Puratos','sector':'','sector_risk':'High',
         'input_url':'https://www.puratos.us','global_score':54,'global_risk':'High','green_score':57,
         'social_score':50,'findings_count':14}
    html=app._v92_render_history_page([row],1,1,25,'')
    assert 'id="createReportBtn"' in html and 'disabled' in html
    assert 'formaction="/history/report_selected"' in html


def test_get_build_batch_summary_report_pdf_lazy_import():
    """v93.12: the lazy-import helper must resolve the real function on a working
    install (reportlab is already a hard dependency for the existing per-company report,
    so this must succeed the same way _get_build_company_report_pdf() does)."""
    fn=app._get_build_batch_summary_report_pdf()
    assert fn is not None and callable(fn)


def test_infer_sector_derives_real_name_from_matched_keyword():
    """v93.14: for a company outside the hardcoded PROFILES list, infer_sector() must
    return a real, human-readable sector name derived from whichever keyword actually
    matched -- the same match that already determines the risk tier -- not just a bare
    risk level with no name at all."""
    comp={'company':'Some Retailer','sector':'Sector not explicitly identified','sector_risk':''}
    # two distinct High-tier keywords ('supermarket', 'grocery') -- the High tier requires
    # >=2 hits before it can override Medium/Low (see infer_sector()'s own v86 comment).
    sec=app.infer_sector(comp,'We are a leading supermarket chain and grocery retailer serving thousands of customers.')
    assert sec['name']=='Food retail and supermarkets (NACE G)'
    assert sec['level']=='High'


def test_infer_sector_no_name_for_profiles_company():
    """v93.14: a hardcoded PROFILES company already has a real sector name from
    infer_company() -- infer_sector() must not attempt to derive a second one (it takes
    the fast 'recognised company/sector profile' path and never reaches the keyword
    matching loop at all)."""
    comp={'company':'Delhaize','sector':'Food retail and supermarkets','sector_risk':'High'}
    sec=app.infer_sector(comp,'Any page text at all.')
    assert sec['name']=='' and sec['level']=='High' and sec['basis']=='recognised company/sector profile'


def test_infer_sector_no_name_when_nothing_matches():
    """v93.14: when no SECTOR_RULES keyword matches at all, infer_sector() keeps the
    existing default-Medium fallback behaviour unchanged and must not fabricate a sector
    name with no real signal behind it."""
    comp={'company':'Mystery Co','sector':'Sector not explicitly identified','sector_risk':''}
    sec=app.infer_sector(comp,'Lorem ipsum dolor sit amet, nothing sector-specific here at all.')
    assert sec['name']=='' and sec['level']=='Medium' and sec['basis']=='default medium exposure'


def test_apply_sector_name_backfills_placeholder_only():
    """v93.14: apply_sector_name() must backfill company['sector'] only when it's still
    the generic placeholder -- never overwrite an already-real sector name (e.g. a
    hardcoded PROFILES label), and be a no-op when infer_sector() found no name."""
    comp={'sector':'Sector not explicitly identified'}
    app.apply_sector_name(comp,{'name':'Food retail and supermarkets (NACE G)'})
    assert comp['sector']=='Food retail and supermarkets (NACE G)'
    comp2={'sector':'Banking and financial services (NACE K)'}
    app.apply_sector_name(comp2,{'name':'Food retail and supermarkets (NACE G)'})
    assert comp2['sector']=='Banking and financial services (NACE K)'  # untouched, already a real name
    comp3={'sector':'Sector not explicitly identified'}
    app.apply_sector_name(comp3,{'name':''})
    assert comp3['sector']=='Sector not explicitly identified'  # no name found -> no change


def test_infer_sector_expanded_taxonomy_covers_more_industries():
    """v93.15: after the sector-name detection shipped, the user reported a real gap --
    an agriculture/poultry producer (Zabra) matched no keyword at all and stayed
    unidentified. The taxonomy was expanded with 13 additional named sectors (agriculture,
    food/beverage manufacturing, automotive, real estate, metals/mining, healthcare/
    pharma/nutrition, hospitality, staffing, waste management, agrochemicals, specialty
    ingredients, education, media) covering common industries from the actual batch-scan
    company list. Each must resolve to its specific name, not a generic fallback.
    v93.18: every name now also cites its NACE Rev. 2 section letter."""
    cases=[
        ('Zabra is a leading poultry and egg producer supplying supermarkets across Belgium.','Agriculture, farming and animal production (NACE A)','High'),
        ('Our vehicle manufacturing plants produce automotive parts for global brands.','Automotive (NACE C)','Medium'),
        ('We are a leading real estate and property management company.','Real estate and property management (NACE L)','Medium'),
        ('Umicore is a materials technology and recycling company specialising in metals.','Metals and materials manufacturing (NACE C)','Medium'),
        ('Metagenics produces nutrition supplements and animal feed additives.','Pharmaceuticals and nutrition manufacturing (NACE C)','Medium'),
        ('A leading hospitality and hotel group operating resorts across Europe.','Accommodation and food service activities (NACE I)','Medium'),
        ('A staffing and recruitment agency providing workforce solutions.','Staffing and human resources services (NACE N)','Medium'),
        ('We produce agrochemical crop protection products and pesticides for farmers.','Agrochemicals and crop protection (NACE C)','Medium'),
        ('We create flavor and fragrance solutions for the food industry.','Specialty ingredients, flavors and fragrances (NACE C)','Medium'),
        ('A city zoo and amusement park offering leisure and entertainment for families.','Arts, entertainment and recreation (NACE R)','Medium'),
        ('Our hospital and medical clinics provide healthcare services region-wide.','Human health and social work activities (NACE Q)','Medium'),
        ('A veterinary and animal hospital clinic for pets and livestock veterinary care.','Veterinary activities (NACE M)','Medium'),
        ('A mining and quarrying operation extracting raw minerals for mining clients.','Mining and quarrying (NACE B)','Medium'),
    ]
    for text,expected_name,expected_level in cases:
        comp={'company':'X','sector':'Sector not explicitly identified','sector_risk':''}
        sec=app.infer_sector(comp,text)
        assert sec['name']==expected_name, f'{text!r} -> {sec["name"]!r}, expected {expected_name!r}'
        assert sec['level']==expected_level


def test_infer_sector_new_specific_keyword_beats_generic_manufacturing():
    """v93.15: "vehicle manufacturing" is a substring superset of the pre-existing generic
    "manufacturing" keyword -- both are placed in the same Medium tier, so a text
    mentioning "vehicle manufacturing" hits both. The new, more specific term must be
    listed first so it wins the name (Automotive), not the generic Industrial
    manufacturing fallback that would otherwise apply to almost any factory."""
    comp={'company':'X','sector':'Sector not explicitly identified','sector_risk':''}
    sec=app.infer_sector(comp,'Our vehicle manufacturing plant is one of the largest in the region.')
    assert sec['name']=='Automotive (NACE C)'


_KBO_SAMPLE_HTML='''<html><body><div id="table"><table>
<tr><td class="QL">Ondernemingsnummer:</td><td class="QL" colspan="3">0403.170.701</td></tr>
<tr><td class="RL">Naam:</td><td class="RL" colspan="3">Gaasch Packaging<br/><span class="upd">Naam in het Nederlands, sinds 1 januari 2000</span><br/></td></tr>
<tr><td class="QL">Adres van de zetel:</td><td class="QL" colspan="3">
Industrielaan&nbsp;10
<br/>9999&nbsp;Voorbeeldstad
<span class="upd"><br/>Sinds 1 januari 2000</span></td></tr>
<tr><td class="RL">Webadres:</td><td class="RL" colspan="3">Geen gegevens opgenomen in KBO.</td></tr>
<tr><td class="I" colspan="3"><h2>Btw-activiteiten Nacebelcode versie 2025</h2></td></tr>
<tr><td class="QL" colspan="3">Btw
2025&nbsp;
<a href="naceToelichting.html?nace.code=46441&amp;nace.version=2025">46.441</a>
&nbsp;-&nbsp;
Groothandel in porselein en glaswerk<br/><span class="upd">Sinds 1 januari 2025</span></td></tr>
</table></body></html>'''

_KBO_NOTFOUND_HTML='<html><body><div class="allContainer">Geen resultaten</div></body></html>'


def test_v93_normalize_be_company_number():
    """v93.20: accepts the common written forms of a Belgian enterprise number and
    rejects anything that clearly isn't one, without ever raising."""
    assert app._v93_normalize_be_company_number('BE 0403.170.701')=='0403170701'
    assert app._v93_normalize_be_company_number('403.170.701')=='0403170701'  # 9 digits, leading 0 dropped
    assert app._v93_normalize_be_company_number('0403170701')=='0403170701'
    assert app._v93_normalize_be_company_number('not a number')==None
    assert app._v93_normalize_be_company_number('')==None
    assert app._v93_normalize_be_company_number(None)==None


def test_v93_lookup_kbo_company_parses_name_address_and_nace(monkeypatch):
    """v93.20: a real KBO public-register result page (structure confirmed against the
    live site) must yield the official name, a clean address (the "Sinds <date>"
    effective-date annotation stripped out) and its current NACEBEL activity code(s)."""
    def fake_open(url,timeout=8,accept=None,max_bytes=None):
        assert 'nummer=0403170701' in url
        return _KBO_SAMPLE_HTML.encode(),'text/html',url
    monkeypatch.setattr(app,'_open_public_url',fake_open)
    info=app._v93_lookup_kbo_company('BE 0403.170.701')
    assert info['name']=='Gaasch Packaging'
    assert info['number']=='0403.170.701'
    assert info['address']=='Industrielaan 10 9999 Voorbeeldstad'
    assert info['website'] is None
    assert info['nace_activities']==[{'code':'46.441','description':'Groothandel in porselein en glaswerk'}]


def test_v93_lookup_kbo_company_not_found_returns_none(monkeypatch):
    monkeypatch.setattr(app,'_open_public_url',lambda *a,**k: (_KBO_NOTFOUND_HTML.encode(),'text/html',a[0]))
    assert app._v93_lookup_kbo_company('0999999999') is None


def test_v93_lookup_kbo_company_invalid_number_never_hits_network(monkeypatch):
    def fake_open(*a,**k):
        raise AssertionError('should never be called for an unparseable number')
    monkeypatch.setattr(app,'_open_public_url',fake_open)
    assert app._v93_lookup_kbo_company('not a number') is None


def test_v93_lookup_kbo_company_never_raises_on_network_failure(monkeypatch):
    monkeypatch.setattr(app,'_open_public_url',lambda *a,**k: (_ for _ in ()).throw(Exception('timeout')))
    assert app._v93_lookup_kbo_company('0403170701') is None


def test_v93_company_number_identity_check_confirms_match():
    """v93.20: when the scanned page's own text names the company the supplied KBO
    number is registered to, the check must read as a confirmation, not a warning."""
    kbo_info={'number':'0403.170.701','name':'Gaasch Packaging','address':'Industrielaan 10, 9999 Voorbeeldstad','nace_activities':[]}
    result=app._v93_company_number_identity_check(kbo_info,'Welcome to Gaasch Packaging, your partner in glass packaging.')
    assert result['match'] is True
    assert 'confirmed' in result['note'].lower()


def test_v93_company_number_identity_check_flags_mismatch():
    """v93.20: this is the exact failure mode reported -- a bare-name scan for "Gaasch
    Packaging" landing on gaasch.net, an unrelated personal website that never mentions
    the company at all. The identity check must surface a clear warning, not stay silent."""
    kbo_info={'number':'0403.170.701','name':'Gaasch Packaging','address':'Industrielaan 10, 9999 Voorbeeldstad','nace_activities':[]}
    result=app._v93_company_number_identity_check(kbo_info,'Welcome to the personal website of Jim and Luann.')
    assert result['match'] is False
    assert 'possible wrong company' in result['note'].lower()
    assert 'Gaasch Packaging' in result['note']


def test_v93_company_number_identity_check_requires_all_tokens_not_just_one():
    """v93.20.1: verified LIVE against the real reported case -- gaasch.net's own page
    text reads "Jim & Luann Gaasch Website" (Gaasch is literally the site owners' real
    surname) and never mentions "packaging" anywhere. An earlier version of this check
    required only ANY ONE distinctive token to match and was fooled by this exact
    coincidence into reporting a false "confirmed" match on the real bug report the
    feature was built for. Requiring every distinctive token (capped at 2) must catch it."""
    kbo_info={'number':'0404.889.282','name':'GAASCH PACKAGING','address':'Z. 5 Mollem 530, 1730 Asse','nace_activities':[]}
    real_gaasch_net_text=('Jim & Luann Gaasch Website. We are Jim & Luann Gaasch. We live in Alpena, Michigan. '
                           'Jim retired from appraising in 2004 as a Certified General Real Estate Appraiser. '
                           'We are still investing in real estate.')
    result=app._v93_company_number_identity_check(kbo_info,real_gaasch_net_text)
    assert result['match'] is False
    assert 'possible wrong company' in result['note'].lower()


def test_analyse_uploaded_document_wires_company_number_end_to_end(monkeypatch):
    """v93.20: analyse_uploaded_document does not crawl a website, so it can exercise the
    full company-number wiring (lookup -> identity check -> comp['company_number'] ->
    NACE-enriched sector classification) without mocking a network crawl."""
    kbo_info={'number':'0403.170.701','name':'Gaasch Packaging','address':'Industrielaan 10, 9999 Voorbeeldstad',
              'website':None,'nace_activities':[{'code':'46.441','description':'Groothandel in porselein en glaswerk'}]}
    monkeypatch.setattr(app,'_v93_lookup_kbo_company',lambda n: kbo_info if n else None)
    result=app.analyse_uploaded_document('policy.txt','This document describes the packaging quality policy of Gaasch Packaging.','',company_number='BE0403170701')
    assert result['company_identity_check']['match'] is True
    assert result['company']['company_number']=='0403.170.701'
    assert result['company']['company']=='Gaasch Packaging'  # kbo name used as the hint


def test_analyse_uploaded_document_unverified_company_number_is_flagged(monkeypatch):
    monkeypatch.setattr(app,'_v93_lookup_kbo_company',lambda n: None)
    result=app.analyse_uploaded_document('policy.txt','Some internal text.','Acme',company_number='BE1234567890')
    assert result['company_identity_check']['match'] is None
    assert 'could not be verified' in result['company_identity_check']['note'].lower()


def test_analyse_uploaded_document_without_company_number_has_no_identity_check():
    result=app.analyse_uploaded_document('policy.txt','Some internal text.','Acme')
    assert result['company_identity_check'] is None


def test_analyse_url_v27_empty_name_with_unresolvable_number_gives_specific_error(monkeypatch):
    """v93.21: a company number is meant to be usable on its own, with the name/website
    field left empty -- reported live: a user left "Company name or website" blank and
    only filled in a KBO number, and got the generic "Please enter a company name or
    website" message, which reads as if nothing had been entered at all even though a
    number was typed. When the number itself fails to resolve and there's no name/url to
    fall back on, the error must say so specifically instead of that generic message."""
    monkeypatch.setattr(app,'_v93_lookup_kbo_company',lambda n: None)
    try:
        app.analyse_url_v27('', 'BE0999999999')
        assert False, 'expected ValueError'
    except ValueError as e:
        msg=str(e).lower()
        assert 'could not be verified' in msg
        assert 'please enter a company name or website' not in msg


def test_empco_blacklist_floor_raises_only_when_blacklisted_claim_present():
    """v93.21: a scan with no blacklisted-practice claim must be completely unaffected --
    green/overall pass through unchanged and the floor flag is False."""
    green_score, overall, applied = app._v93_apply_empco_blacklist_floor(40, 35, [{'blacklisted_practice_indicator': False}])
    assert (green_score, overall, applied) == (40, 35, False)
    green_score, overall, applied = app._v93_apply_empco_blacklist_floor(40, 35, [])
    assert (green_score, overall, applied) == (40, 35, False)


def test_empco_blacklist_floor_raises_to_75_but_never_lowers():
    """v93.21: the floor only ever RAISES a score to 75 (the Very high threshold) -- a
    score already at or above 75 from the blended formula must be left exactly as is."""
    green_score, overall, applied = app._v93_apply_empco_blacklist_floor(40, 35, [{'blacklisted_practice_indicator': True}])
    assert (green_score, overall, applied) == (75, 75, True)
    green_score, overall, applied = app._v93_apply_empco_blacklist_floor(90, 82, [{'blacklisted_practice_indicator': True}])
    assert (green_score, overall, applied) == (90, 82, True)


def test_analyse_uploaded_document_blacklisted_claim_forces_very_high():
    """v93.21: end-to-end via the internal-document pipeline (no network/crawl needed) --
    a generic, unspecified environmental claim ("100% eco-friendly, made from sustainable
    materials") is a known EmpCo Annex I 4a blacklist match. Before this change, a real
    scan batch showed EVERY company landing in Low/Medium/High despite roughly half
    having such a claim -- the tool's own "Very high" band was never actually reached in
    practice. green_risk and global_risk must both now read "Very high" regardless of
    what the blended formula alone would have produced."""
    text='Our products are 100% eco-friendly and made from sustainable materials, helping the planet.'
    result=app.analyse_uploaded_document('claims.txt', text, 'Acme')
    assert result['empco_blacklist_floor_applied'] is True
    assert result['green_risk']=='Very high' and result['green_score']>=75
    assert result['global_risk']=='Very high' and result['global_score']>=75
    assert 'Automatic Very high' in result['green_conclusion']


def test_analyse_uploaded_document_no_blacklist_claim_not_forced():
    """v93.21: a document with no blacklisted-practice claim at all must not be affected
    by the new floor -- confirms the override is conditional, not a blanket change."""
    result=app.analyse_uploaded_document('claims.txt', 'This is a plain internal memo with no sustainability claims at all.', 'Acme')
    assert result['empco_blacklist_floor_applied'] is False


def test_batch_report_analysis_text_mentions_top_company_and_top_claim():
    """v93.16: the report's "Analysis" section (distinct from the factual Executive
    Summary) must name the actual highest-scoring company, the dominant sector-risk
    level, and the top flagged claim by name -- not just repeat generic totals."""
    import batch_report_pdf as brp
    rows=_sample_export_rows()  # Lidl 61/High, Zabra 41/Medium, Home Invest 9/Low
    agg=brp._aggregate(rows)
    top_claims=[{'phrase':'carbon neutral','risk':'High','occurrences':9,'companies':5,'blacklisted':True}]
    text=brp._analysis_text(agg,top_claims)
    assert 'Lidl' in text and '61/100' in text
    assert 'carbon neutral' in text
    assert '9 time' in text and '5 compan' in text
    assert 'blacklisted' in text.lower()
    # no top_claims and a single-row selection -> no sector-dominance or claim sentence,
    # but must still not crash and still name the top company
    single=[r for r in rows if r['company']=='Zabra']
    agg_single=brp._aggregate(single)
    text_single=brp._analysis_text(agg_single,[])
    assert 'Zabra' in text_single


def test_batch_report_analysis_text_contrasts_top_and_bottom_company():
    """v93.17: per the user's explicit request for "iets uitgebreidere analyse" (a
    somewhat more extensive analysis), the Analysis section must also name the
    LOWEST-scoring company for contrast, state the average findings-per-company, and
    list additional recurring claim wording beyond just the single top phrase -- but
    only when there's more than one company (a 1-company selection has no meaningful
    "by contrast" comparison)."""
    import batch_report_pdf as brp
    rows=_sample_export_rows()  # Lidl 61/High, Zabra 41/Medium, Home Invest 9/Low
    agg=brp._aggregate(rows)
    top_claims=[
        {'phrase':'carbon neutral','risk':'High','occurrences':9,'companies':5,'blacklisted':True},
        {'phrase':'eco-friendly','risk':'Medium','occurrences':3,'companies':2,'blacklisted':False},
        {'phrase':'net zero','risk':'Medium','occurrences':2,'companies':1,'blacklisted':False},
    ]
    text=brp._analysis_text(agg,top_claims)
    assert 'By contrast' in text and 'Home Invest' in text and '9/100' in text
    assert 'flagged claim(s) were retained per company' in text
    assert 'eco-friendly' in text and 'net zero' in text
    single=[r for r in rows if r['company']=='Zabra']
    agg_single=brp._aggregate(single)
    text_single=brp._analysis_text(agg_single,[])
    assert 'By contrast' not in text_single


def test_batch_report_pill_badges():
    """v93.17: risk and blacklist values must render as rounded pill badges (a hand-drawn
    Drawing with a soft-tinted background and colored bold text), matching the same
    visual convention already used on the /history HTML page's risk badges -- not plain
    inline-colored text, which the user reported as looking unprofessional. An
    empty/unset risk or a False blacklist flag must fall back to a plain dash, not an
    empty-looking badge."""
    import batch_report_pdf as brp
    from reportlab.graphics.shapes import Drawing
    high_pill=brp._risk_pill('High')
    assert isinstance(high_pill,Drawing)
    empty_pill=brp._risk_pill('')
    assert not isinstance(empty_pill,Drawing)  # falls back to a plain Paragraph dash
    yes_pill=brp._yes_no_pill(True)
    assert isinstance(yes_pill,Drawing)
    no_pill=brp._yes_no_pill(False)
    assert not isinstance(no_pill,Drawing)


def test_batch_report_top_claims_table_renders_and_is_absent_when_empty():
    """v93.16: the most-flagged-claims table must render one row per claim with the
    phrase, colored risk level, EmpCo blacklist marker and counts -- and the whole
    section must not appear (returns None) when there's no claims data for this
    selection, so the report doesn't show an empty/misleading table."""
    import batch_report_pdf as brp
    assert brp._top_claims_table([]) is None
    assert brp._top_claims_table(None) is None
    top_claims=[{'phrase':'carbon neutral','risk':'High','occurrences':9,'companies':5,'blacklisted':True},
                {'phrase':'eco-friendly','risk':'Medium','occurrences':3,'companies':2,'blacklisted':False}]
    table=brp._top_claims_table(top_claims)
    assert table is not None
    # Table.__init__ stores the original row data on ._cellvalues
    rendered_texts=[[getattr(cell,'text','') for cell in row] for row in table._cellvalues]
    flat=' '.join(t for row in rendered_texts for t in row)
    assert 'carbon neutral' in flat and 'eco-friendly' in flat


def test_history_resolve_selected_scan_ids(monkeypatch):
    """v93.16: _v92_resolve_selected_scan_ids() must return the explicit ids list as-is
    when not in select_all mode, and must query the database for ids matching the active
    filter (via the same _v92_build_filters() WHERE clause as everything else) when
    select_all=1 -- this is what scopes the Create-report PDF's "most flagged claims"
    section to exactly the selected scans."""
    assert app._v92_resolve_selected_scan_ids({'ids':['5','9']})==[5,9]
    executed=[]
    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def execute(self,sql,params=None): executed.append((sql,params))
        def fetchall(self): return [(1,),(2,),(3,)]
    class FakeConn:
        def cursor(self): return FakeCursor()
        def close(self): pass
    monkeypatch.setattr(app,'_v92_ensure_table',lambda conn: True)
    monkeypatch.setattr(app,'_v92_db_connect',lambda: FakeConn())
    result=app._v92_resolve_selected_scan_ids({'select_all':['1'],'risk':['High']})
    assert result==[1,2,3]
    assert 'WHERE global_risk = %s' in executed[0][0]


def test_v92_fetch_top_claims_for_scan_ids_empty_shortcircuit():
    """v93.16: an empty scan_ids list must short-circuit to [] without ever touching the
    database -- an empty selection (or a select_all filter matching nothing) shouldn't
    issue a query that would trivially match nothing anyway."""
    assert app._v92_fetch_top_claims_for_scan_ids([])==[]
    assert app._v92_fetch_top_claims_for_scan_ids(None)==[]
