# Durably Sustainability Scan - v69

V69 corrects the PDF-download signature regression and makes the negative-news restriction for external public-source signals enforceable throughout the complete output pipeline.

Expected health version:

`hostable_v69_report_token_strict_negative_external_signals`

Read `START_HERE_V69.md`, `V69_CHANGELOG.md`, `DEPLOY_V69.txt` and `TEST_RESULTS_V69.txt` before deployment.

## Main v69 changes

- Opaque, compressed and signed report token for reliable two-page PDF downloads.
- Report token survives browser JSON parsing and number normalisation.
- Deterministic fallback key prevents restart-related failures when no production secret is configured.
- Negative-polarity filtering before external results are ranked or retained.
- Positive achievements, partnerships, awards, certifications, launches and neutral coverage are excluded.
- Exoneration and dismissed-allegation articles are excluded.
- Negative-only enforcement in backend, frontend and PDF report.
- All previous crawler, entity-lock, claim-signal, source-register, methodology and layout improvements are retained.

The scan is an indicative first-pass assessment. It is not legal advice and does not establish a breach of EmpCo, the Forced Labour Regulation or any other law.
