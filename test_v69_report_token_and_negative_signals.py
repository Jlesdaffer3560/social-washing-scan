import json
import app


def test_report_token_survives_browser_style_round_trip():
    payload={
        'company':{'company':'Example Group'},
        'global_score':47.0,
        'score_components':{'external_context_risk':12.0,'weights':[1.0,2.5]},
    }
    app.attach_report_signature(payload)
    assert payload.get('_report_token')
    # JSON parsing/stringifying in a browser must not require the browser to reproduce
    # Python's exact float spelling or key ordering. The opaque token is unchanged.
    browser_roundtrip=json.loads(json.dumps(payload))
    decoded=app.decode_report_token(browser_roundtrip['_report_token'])
    assert decoded['global_score']==47.0
    assert decoded['score_components']['weights']==[1.0,2.5]


def test_report_token_detects_tampering():
    payload={'company':{'company':'Example Group'},'global_score':55}
    app.attach_report_signature(payload)
    token=payload['_report_token']
    replacement=('A' if token[-1]!='A' else 'B')
    try:
        app.decode_report_token(token[:-1]+replacement)
    except ValueError as exc:
        assert 'invalid' in str(exc).lower()
    else:
        raise AssertionError('Tampered report token must be rejected')


def test_positive_green_article_is_excluded():
    result={
        'title':'Example Fashion achieves carbon-neutral operations across global sites',
        'content':'The company celebrates a sustainability milestone and receives certification.',
        'url':'https://news.example/example-fashion-carbon-neutral-achievement',
    }
    assert not app.is_green_negative_source(result)


def test_positive_social_article_is_excluded():
    result={
        'title':'Example Fashion launches worker well-being partnership',
        'content':'The company announced a collaboration and new initiative for suppliers.',
        'url':'https://news.example/example-fashion-worker-partnership',
    }
    assert not app.is_negative_external_source(result)


def test_negative_regulator_and_worker_articles_are_retained():
    green={
        'title':'Example Fashion fined for misleading environmental claims',
        'content':'The competition authority fined Example Fashion after finding misleading sustainability claims.',
        'url':'https://regulator.example/example-fashion-fine',
    }
    social={
        'title':'NGO report alleges illegal working hours at Example Fashion suppliers',
        'content':'Workers reported excessive working hours, low wages and labour-rights violations.',
        'url':'https://ngo.example/example-fashion-workers',
    }
    assert app.is_green_negative_source(green)
    assert app.is_negative_external_source(social)


def test_retained_external_result_set_contains_only_negative_sources():
    company='Example Fashion'
    reviewed=['https://www.examplefashion.com']
    results=[
        {
            'title':'Example Fashion achieves carbon-neutral operations',
            'content':'Example Fashion celebrates a sustainability milestone and certification.',
            'url':'https://news.example/example-fashion-carbon-neutral',
        },
        {
            'title':'Example Fashion fined for misleading environmental claims',
            'content':'The regulator fined Example Fashion after finding misleading sustainability claims.',
            'url':'https://regulator.example/example-fashion-fine',
        },
    ]
    retained=app._v60_rank_dedupe(results,company,'green',20,reviewed)
    assert [r['title'] for r in retained]==['Example Fashion fined for misleading environmental claims']
    compact=app.compact_sources(retained,5,'green')
    assert compact and all(r.get('polarity')=='negative' for r in compact)


def test_exoneration_headline_is_not_negative_news():
    result={
        'title':'Example Fashion cleared of forced labour allegations',
        'content':'The authority found no evidence of forced labour after its investigation.',
        'url':'https://news.example/example-fashion-cleared',
    }
    assert not app.is_negative_external_source(result)
