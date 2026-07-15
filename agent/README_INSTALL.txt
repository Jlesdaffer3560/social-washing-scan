Durably Sustainability Scan — v55 final updated package

Replace in your GitHub/Render project:
  app.py, agent.py, durably_sustainability_scan.py, frontend.html, methodology.pdf

Then commit, push, and redeploy on Render.
Check /api/health for: hostable_v55_claim_detection_balanced_report_layout

WHAT CHANGED
Backend (app.py):
- Single APP_VERSION throughout (removed stale v54 reassignments)
- Bug fix: company name now correctly passed to external context scoring
- Removed duplicate _v55_sentence_list definition
- External search expanded from 3 to 6 queries per scan
- EU Green Claims Directive (GCD) added as a distinct regulatory lens
- EUDR added with dedicated claim pattern (deforestation-free, EUDR compliant etc.)
- CSDDD updated for Omnibus I: >5,000 emp AND >EUR1.5B; application 26 July 2029
- CSRD updated for Omnibus I: >1,000 emp AND >EUR450M; reporting from FY2027

Frontend (frontend.html):
Interface improvements:
- Score cards: progress bars + score interpretation text added
- Section headers: visual left-bar separators
- Hero: improved gradient and spacing
- Download panel: more prominent styling
- Input field: focus state with teal ring
- Status: version badge with 5s timeout

2-page PDF report (completely redesigned):
- Full-width navy header bar on each page with source and date
- 4-box score grid: Global / Green / Social + Overall Risk Level
- Progress bars inside score boxes
- Color-coded risk pill badges on each claim
- Green claim cards with green left border; social with amber
- Score component driver table (both green and social)
- External stakeholder signals section
- Numbered action plan with title + description
- Score interpretation bands (0-29 / 30-49 / 50-69 / 70-84 / 85-100)
- Methodology note with correct v55 weights (42/24/22/12)
- Print-safe color rendering (print-color-adjust: exact)

Methodology PDF (fully rewritten):
- All 6 regulatory lenses including GCD and EUDR
- Omnibus I thresholds for CSDDD and CSRD
- Correct v55 scoring weights (42/24/22/12)
- Score bands and interpretation

TIMEOUT FIX (latest update)
- fetch_html timeout: 7s -> 5s with helpful error message
- Tavily and Google Search timeouts: 7s -> 5s
- External search queries: 6 -> 4 per scan
- Crawl: reduced from 3 to 2 additional pages per scan
- Document fetch timeout: 10s -> 7s
- Better error message when website times out:
  "Website scan timed out. Try the sustainability page directly,
   or paste text into a document and use the document scan."
