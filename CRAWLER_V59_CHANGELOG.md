# v59 — Resilient multi-page crawler

## Problem addressed

Earlier versions stopped after the first three candidate sub-pages. When those first
candidates returned HTTP 403, 404 or time-outs, the scan could finish with only the
homepage even when other valid sustainability, ESG or reporting pages were available.

## Changes

- The crawler now aims for six additional usable pages by default.
- It can test up to fourteen ranked candidate URLs instead of stopping after the first
  three attempts.
- Failed pages no longer consume the full successful-page allowance.
- Internal links, robots.txt, sitemap.xml, sitemap indexes, child sitemaps, common public
  paths and relevant PDF reports are combined in one ranked queue.
- Sitemap `.gz` files and `www` / non-`www` canonical differences are supported.
- Candidate pages are fetched in small concurrent batches so slow blocked pages do not
  exhaust the complete Render request window.
- Direct page requests use browser-like headers and one conservative retry.
- When enabled, blocked or JavaScript-heavy public pages can use Jina Reader as a
  text-extraction fallback. This is recorded in crawl diagnostics.
- Related-domain guesses are used only when primary-site coverage remains limited.
- The data-reliability warning remains in place. It still includes the sentence:

  > A low risk score from this scan may reflect limited access to the site's content,
  > not necessarily a genuine absence of risky claims.

## Optional Render environment variables

- `CRAWL_TARGET_EXTRA_PAGES=6`
- `CRAWL_MAX_PAGE_ATTEMPTS=14`
- `CRAWL_BUDGET_SECONDS=24`
- `CRAWL_FETCH_WORKERS=4`
- `ENABLE_READER_FALLBACK=1`
- `JINA_API_KEY=` (optional; only needed for higher Reader API limits)

The defaults work without adding environment variables.
