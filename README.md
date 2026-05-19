# Social Claim Risk Scan Hostable V15

Upload these five files to the ROOT of your GitHub repository:

- app.py
- frontend.html
- requirements.txt
- render.yaml
- README.md

Render:
- Runtime: Python
- Build command: pip install -r requirements.txt
- Start command: python app.py

Environment variable for external search:
- TAVILY_API_KEY

After deployment, click Check backend. It should show:
Backend OK. Version: hostable_v19. AI configured: false. Tavily configured: true


V15 improvements:
- Standards lens: CSRD/ESRS, CSDDD, OECD Guidelines, UNGPs, UNGC, ILO and GRI.
- Shorter public-source signals while keeping source links.
- Clearer claim excerpts and more actionable claim-level findings.
- More concise, executive-style report output.


V15 improvements:
- Risk scoring is more conservative and claim-focused.
- Sector risk and external public-source signals are modifiers only, not automatic high-risk triggers.
- High scores should mainly occur when the website contains broad, absolute or poorly substantiated social claims.
- Claim scores reduced and thresholds adjusted.


V15 improvements:
- External public-source signals can meaningfully affect the score when they are relevant to the concrete company and detected claim themes.
- External sources are scored through a capped modifier, so they inform the result without replacing claim-level analysis.
- The report shows the external-source contribution separately for transparency.


V15 improvements:
- Split scoring into claim wording risk, external context risk and sector baseline risk.
- Adds claim inventory with evidence checklist and suggested safer wording.
- Adds investor red flags and company action plan.
- Adds engagement questions for investors/stewardship.
- Adds source credibility labels for external public-source signals.
- Adds assessment confidence level.
- Improves HTML/text report structure.


V16 improvements:
- Adds Google Custom Search JSON API as fallback when Tavily fails, returns no results, is not configured, or hits a limit.
- Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX in Render.
- Backend health check reports Google Search configuration.
- External source cards and reports show which provider was used.


V17 improvements:
- Overall score is now explicitly shown as an integrated score made up of claim wording risk, external context risk and sector baseline risk.
- External context risk is stricter: very high only where serious and repeated allegations focus on the company.
- Company wording is shown between quotation marks.
- Engagement section removed.
- Standards lens moved higher and shortened.
- Detected social claims and claim-level findings merged into one claims review section.
- Professional report rewritten to be clearer, shorter and more executive.
- Footer added: produced by Jordi Lesaffer, Novarisq Consulting, May 2026.

V18 improvements:
- Result and integrated score sections merged; the overall score remains visually dominant.
- “Investor” terminology replaced by “Stakeholder”.
- Company website input is empty on page load.
- Scan subtitle now explains social washing as the social/human-rights equivalent of greenwashing.
- Claims review remains merged and company wording is clearly quoted.
- Professional report layout rewritten for a clearer, concise PDF-style output.

V19 improvements:
- Social-washing risk review label made more visible.
- Assessment summary is company-specific and based on detected claims, sector context and negative external signals.
- Removed stale AI/scoring generic text.
- Why-this-score section now has bold categories: claim wording, external context, sector context and interpretation.
- Public-source section retains only negative or risk-relevant signals.
- Claims review analysis is more concrete and tied to company wording.
- Professional report rewritten with clearer numbering, stronger executive layout and concise content.
