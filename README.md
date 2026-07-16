# Durably Sustainability Scan - v66

Current version: `hostable_v66_claim_risk_badge_layout_fix`

v66 definitively fixes the claim-card risk label that could appear outside the right-hand border. The risk level is now rendered as a fixed-width coloured badge on the left of each claim title.

Read `V66_CHANGELOG.md`, `DEPLOY_V66.txt` and `TEST_RESULTS_V66.txt` first.

---

# Durably Sustainability Scan — V64

V64 fixes cross-company entity contamination and restores official-site claim coverage. Read `V64_CHANGELOG.md`, `DEPLOY_V64.txt` and `TEST_RESULTS_V64.txt` first.

# Durably Sustainability Scan — v62

Current version: `hostable_v62_professional_claim_signals_readable_pdf`

## Main capabilities

- Multi-page public website scan with resilient crawling and transparent coverage diagnostics.
- Separate website and internal-document assessments.
- Green, social and combined claim-risk scores.
- Structured claim signals under EmpCo environmental, social-characteristics, forced-labour/supply-chain and other-claim sections.
- External public-source search with company-ownership exclusion, entity matching, negative-polarity validation and duplicate-event clustering.
- Separate entity context, confidence and data-reliability reporting.
- Native, readable and exactly two-page company PDF report.
- Detailed methodology PDF at `/methodology.pdf`.

## Render deployment

Replace the current repository files with this package, commit and push. Render should redeploy automatically.

Health check: `/api/health`

Expected version: `hostable_v62_professional_claim_signals_readable_pdf`

The scan is an indicative first-pass assessment. It is not legal advice and does not establish a breach of EmpCo, the Forced Labour Regulation or any other law.
