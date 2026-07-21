# Start here — Durably Sustainability Scan v72

This release contains two changes. See V72_CHANGELOG.md for full detail.

1. A prohibited-vs-problematic legal-basis classification on every claim, surfaced on
   the dashboard.
2. A fix for bare-name company resolution ("Scan failed: Official domain for X could
   not be verified with sufficient confidence"), which was hard-blocking scans for any
   company outside a 4-name whitelist (Shein/H&M/Zara/Inditex).

## Deploy

1. Copy the changed files into your local repo folder, overwriting the existing ones:
   `app.py`, `frontend.html`, `test_v62.py`, `test_v68_pytest.py`,
   `test_v68_stability.py`, `test_v70_report_readability.py`.
2. Open GitHub Desktop. It should show those files plus `V72_CHANGELOG.md` and
   `START_HERE_V72.md` as changed/new.
3. Commit (e.g. "V72: legal-basis classification + bare-name resolution fix") and
   push to `main`.
4. Render will redeploy automatically. Once live, confirm `/api/health` returns:
   - release: v72
   - version: hostable_v72_legal_basis_classification

## Test 1 — legal-basis classification

Run a scan on a company with known green claims (e.g. one with an offsetting or
"eco-friendly" claim on its site). On the dashboard, under the claims section, confirm
you see:
- A box at the top with two counts: "Prohibited (EmpCo Annex I)" and "Problematic, not
  prohibited (case-by-case)", plus a short explanation.
- A red "Prohibited (Annex I)" or amber "Problematic (case-by-case)" badge on each
  individual claim card, next to the existing topic badge.
- A "Legal basis" box inside each claim's expanded detail view.

## Test 2 — bare-name resolution

Start a scan with just the name "Puratos" (no URL). It should now resolve to
puratos.com and proceed — check the banner at the top of the results for a resolution
note. It should never show "Scan failed: Official domain ... could not be verified"
again, for Puratos or any other company.

Optional but recommended: check `/api/health` for `tavily_configured` and
`google_search_configured`. If both are false, no search provider is set up on this
deployment at all — worth adding TAVILY_API_KEY or GOOGLE_SEARCH_API_KEY +
GOOGLE_SEARCH_CX in Render's environment variables so bare-name resolution can use
verified search matches too, in addition to the new fallback.

## Test 3 — flagship domain over regional domain

Check the "resolved to..." note at the top of the Puratos scan result: it should say
`www.puratos.com`, not `www.puratos.be`. If it still says `.be`, re-run the scan once
more — a transient timeout on `.com` during that specific run can still happen; the
important part is it should no longer be a fixed 100%-of-the-time outcome.

No environment variables or credentials changed by this release. No data migration
needed.

Rollback: redeploy v71.
