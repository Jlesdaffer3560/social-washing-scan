# V70 changelog — report readability and external-source precision

Release date: 19 July 2026

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
