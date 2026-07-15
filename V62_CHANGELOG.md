# V62 — Structured claim signals and readable two-page report

Version: `hostable_v62_professional_claim_signals_readable_pdf`

## Key sustainability claim signals

- Replaced the repetitive open-card list with four clear sections:
  1. EmpCo — Environmental claims
  2. Social characteristics
  3. Forced labour and supply-chain assurance
  4. Other sustainability claims
- Added thematic subcategories within each section.
- High- and medium-risk social signals remain in the correct social section; risk level no longer changes the legal grouping.
- Added a compact summary showing material occurrences, high-risk signals, medium-risk signals and consumer-facing signals.
- Clustered repeated occurrences of the same claim type.
- Claim rows are closed by default and show the main evidence gap immediately.
- Removed the duplicate “at a glance” block, numbered steps, repeated trigger list and “Problematic signal” wording.
- Added audience and regulatory-lens badges.
- Limits the initial view to five claim groups per section, with a “Show more” control.

## External public-source signals

- Added word/phrase-boundary matching to prevent false positives such as `ban` in `banner`.
- A relevant green/social anchor and demonstrably negative polarity are both required.
- Neutral or positive sustainability announcements are not retained as negative external signals.
- Added structured fields: source, date, event status, review status, entity match, dimension, relevance and related claim area.
- Removed common search-result and website boilerplate from signal summaries.
- Candidate search results do not affect scores. Only retained signals are used in entity-context scoring; “Verified” is reserved for manually verified records.

## Data reliability

- The caution remains explicit: “A low risk score from this scan may reflect limited access to the site's content, not necessarily a genuine absence of risky claims.”
- The warning is now triggered when more than 25% of attempts fail, fewer than three relevant pages are reviewed, thin pages are returned or a text-extraction fallback is used.
- The two-page PDF displays the warning as a separate yellow section.

## Two-page company report

- Minimum body font: 9 pt.
- Claim excerpts: 8.5 pt.
- Tables: 8 pt.
- Sources and metadata: at least 7.5 pt.
- Footer: 6.5 pt.
- Duplicate claim types are clustered in the executive summary, risk drivers and material finding.
- External signals have a dedicated section with structured status and source information.
- Confidence reasons are punctuated and readable.
- Full URLs are replaced with concise source labels.
- A post-generation page-count check uses `pypdf`. If content would create a third page, detail is progressively limited; font sizes are never reduced.
