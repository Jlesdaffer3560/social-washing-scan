Durably Sustainability Scan - v55 updated package

WHAT CHANGED IN THIS BUILD
- Single APP_VERSION throughout file (removed stale v54 reassignments)
- Bug fix: strict_external_context_risk() now receives correct company name
  in all call paths (previously received empty string, suppressing company
  matching in external context scoring)
- Removed duplicate _v55_sentence_list definition (dead code)
- External search expanded from 3 to 6 queries per scan
- EU Green Claims Directive (GCD, 2024) added to EMPCO_LENS
- EU Deforestation Regulation (EUDR) added as a distinct claim lens
  with dedicated claim pattern (deforestation-free, EUDR compliant, etc.)
- CSDDD and CSRD thresholds updated for Omnibus I (Directive 2026/470,
  in force 18 March 2026): CSDDD scope is now >5,000 employees AND
  >EUR1.5B net turnover (application from 26 July 2029); CSRD scope is
  >1,000 employees AND >EUR450M net turnover (reporting from FY2027)
- globals() guards removed (clean code)
- Frontend: regulatory kicker and description updated to include GCD and EUDR
- Frontend: version badge timeout added (5s)
- Frontend: 2-page print report now includes score interpretation bands
  and updated methodology note
- Methodology PDF: full rewrite with all regulatory updates, GCD and EUDR
  sections, correct v55 scoring weights (42/24/22/12), Omnibus I note

DEPLOY TO RENDER
Replace the following files in your GitHub/Render project:
- app.py
- agent.py
- durably_sustainability_scan.py
- frontend.html
- methodology.pdf

Then commit, push, and redeploy on Render.

After deployment, check /api/health. It should show:
hostable_v55_claim_detection_balanced_report_layout
