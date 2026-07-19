# V70 changelog — report readability and external-source precision

Release date: 19 July 2026

- **Added:** green claims now carry a reader-facing EmpCo legal classification —
  **"Prohibited (per se)"** for UCPD Annex I blacklist practices (generic unsubstantiated
  claims, offset-based neutrality claims such as "carbon neutral", self-declared
  sustainability labels, and legal requirements presented as a voluntary benefit), versus
  **"Misleading (case-by-case)"** for claims assessed individually under the amended UCPD
  Art. 6/7 (absolute/purity wording such as "fully recyclable", comparative claims, and
  future/aspirational claims without a public implementation plan). The underlying
  per-claim signal already existed (`blacklisted_practice_indicator`) but was never shown
  to the reader; it now appears as a labelled line on each claim card in the PDF report
  and as a colour-coded badge with an expandable legal basis in the web report. Verified
  against the EU Commission's EmpCo FAQ and Annex I point numbering (4a/4b/4c/2a). Covered
  by new regression tests, including a PDF text-overflow check.

## Post-release fixes (reviewed 19 July 2026)

- **Fixed:** `is_negative_external_source` rejected unambiguous, event-framed adverse
  headlines (e.g. "Modern slavery uncovered in ...", "Child labour found at ...") unless
  a *second*, separate legal/enforcement word also appeared -- unlike the green branch,
  where an explicit headline term was already sufficient on its own. An explicit adverse
  term in the headline is now accepted by itself, unless the headline reads as a
  self-descriptive policy/compliance-document title (e.g. "Modern Slavery and Human
  Trafficking Policy"), which remains excluded. Covered by a new regression test.
- **Fixed:** `score_driver_details(...)` was being computed three times with identical
  arguments in both `analyse_uploaded_document` and `analyse_url_v27`, instead of being
  computed once and reused. No behaviour change; removes redundant work on every scan.
- **Cleaned up:** 15 function names (`is_negative_external_source`,
  `is_company_owned_source`, `targeted_negative_sources`, `resolve_company_website`,
  `infer_company`, `crawl_with_related_sites`, and others) had 2-4 full duplicate
  definitions accumulated across earlier version increments. Python always runs the
  *last* definition in the file, so the earlier copies were silently dead code -- a real
  risk, since a future patch could edit a shadowed copy and have zero effect. Removed all
  34 dead definitions (~655 lines) and confirmed zero behaviour change: full test suite
  (pytest + all standalone v62-v68 regression scripts) passes identically before and
  after, and no default-argument or module-level binding depended on an earlier copy.

## Reader-facing report

- Removed the internal build label and external-search configuration status.
- Rewrote the assessment summary to explain what was reviewed, the detected risk level and the main review priorities without repeating channel-classification language.
- Reduced score drivers to a short summary and at most four clearly labelled factors per dimension.
- Grouped and deduplicated red flags, limited each group to core findings, and hid empty categories.
- Reworked recommended-action cards with priority pills, clearer hierarchy and selective term highlighting.
- Removed the source-register explanation and CSV download.
- Removed internal search diagnostics from the external-signal section.
- Increased previously undersized labels, badges, notes and detail text.

## External-source controls

- Added country-code-aware brand-domain recognition, including domains such as `puratos.co.uk`.
- Treats brand-led microsites such as `puratosgrandplace.com` as first-party unless the domain clearly belongs to an independent watchdog, rights group, campaign or worker organisation.
- Requires a concrete adverse event, allegation, criticism or formal action for social external signals; policy vocabulary by itself is insufficient.
- Added a final reader-interface safeguard that suppresses company, corporate, official and policy sources from external signals.

## Regression coverage

- Added Puratos-specific tests for the previously observed company-policy false positives.
- Added a positive control proving that a genuine independent adverse authority source remains eligible.
- Added checks for the removed internal copy, increased type sizes and new action emphasis.
