# V64 — Entity lock and internal-claims recovery

## Root causes corrected

1. **Unsafe official-domain resolution** — a bare company name previously accepted the first non-directory search result. A competitor domain could therefore become the scanned entity.
2. **Company inference from page text** — known competitor names in page content could replace the company identified by the reviewed host.
3. **Weak external entity matching** — a source was accepted when the target appeared once anywhere in the snippet, even if the title and incident concerned another company.
4. **Retail-site crawl starvation** — JavaScript-heavy or blocked storefronts could consume the crawl budget before the official corporate sustainability site was checked.

## V64 behaviour

- Brand/domain scoring for bare-name resolution; competitor domains are rejected.
- Company identity remains anchored to the reviewed official root throughout the scan.
- Direct external entity match requires the target in the title/URL, or repeated target references with nearby controversy language and no competitor-primary title.
- Competitor-primary search results are counted in diagnostics but never displayed or scored.
- Official group/corporate sites are crawled with reserved time. SHEIN retail pages are supplemented with `sheingroup.com` sustainability pages.
- Company-owned corporate pages remain internal evidence and are excluded from external stakeholder signals.
- Existing internal green/social claim detectors are regression-tested end to end.
