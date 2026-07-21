# Start here — Durably Sustainability Scan v72

This release adds a prohibited-vs-problematic legal-basis classification to every
claim, and surfaces it on the dashboard. See V72_CHANGELOG.md for full detail.

1. Copy the two changed files into your local repo folder, overwriting the existing
   ones: `app.py` and `frontend.html`.
2. Open GitHub Desktop. It should show `app.py`, `frontend.html`,
   `V72_CHANGELOG.md`, `START_HERE_V72.md`, `test_v68_pytest.py` and
   `test_v70_report_readability.py` as changed/new files.
3. Commit (e.g. "V72: prohibited vs. problematic legal-basis classification") and
   push to `main`.
4. Render will redeploy automatically. Once live, confirm `/api/health` returns:
   - release: v72
   - version: hostable_v72_legal_basis_classification
5. Run a scan on a company with known green claims (e.g. one with an offsetting or
   "eco-friendly" claim on its site). On the dashboard, under the claims section,
   confirm you see:
   - A new box at the top with two counts: "Prohibited (EmpCo Annex I)" and
     "Problematic, not prohibited (case-by-case)", plus a short explanation.
   - A red "Prohibited (Annex I)" or amber "Problematic (case-by-case)" badge on
     each individual claim card, next to the existing topic badge.
   - A "Legal basis" box inside each claim's expanded detail view.
6. No environment variables or credentials changed. No data migration needed.

Rollback: redeploy v71.
