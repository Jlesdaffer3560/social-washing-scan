"""Offline smoke tests for the v59 crawler. Run: python test_crawler_v59.py"""
import json
import time
import app


def test_continues_after_first_three_failures():
    links=''.join(f'<a href="/sustainability/page{i}">Page {i}</a>' for i in range(1,9))
    original_fetch_html=app.fetch_html
    original_discover=app.discover_sitemap_urls
    original_fetch_page=app.fetch_page_content
    try:
        app.fetch_html=lambda url,timeout=7: '<html><body>'+('sustainability evidence '*100)+links+'</body></html>'
        app.discover_sitemap_urls=lambda url,limit=160,deadline=None: []
        def fake_fetch(url,timeout=7):
            number=int(url.rsplit('page',1)[1])
            if number <= 3:
                raise ValueError('blocked')
            return 'Evidence '*100,'html','direct'
        app.fetch_page_content=fake_fetch
        log=[]
        _,pages=app.crawl('https://example.com',max_extra_pages=4,deadline=time.time()+10,log=log)
        assert len(pages)==5, pages
        assert sum(not x['ok'] for x in log)>=3
    finally:
        app.fetch_html=original_fetch_html
        app.discover_sitemap_urls=original_discover
        app.fetch_page_content=original_fetch_page


def test_warning_is_preserved():
    confidence=app.build_confidence(
        ['https://example.com'],
        {'enabled':False,'results':[]},
        [],
        [
            {'ok':True,'thin':False,'method':'direct'},
            {'ok':False,'thin':False},
            {'ok':False,'thin':False},
            {'ok':False,'thin':False},
        ],
    )
    required=("A low risk score from this scan may reflect limited access to the site's "
              "content, not necessarily a genuine absence of risky claims.")
    assert required in confidence.get('reliability_warning','')


if __name__=='__main__':
    test_continues_after_first_three_failures()
    test_warning_is_preserved()
    print(json.dumps({'status':'ok','version':app.APP_VERSION},indent=2))
