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
Backend OK. Version: hostable_v15. AI configured: false. Tavily configured: true


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
