# Social Claim Risk Scan Hostable v10

Upload these five files to the ROOT of GitHub:

- app.py
- frontend.html
- requirements.txt
- render.yaml
- README.md

Render:
- Runtime: Python
- Build command: pip install -r requirements.txt
- Start command: python app.py
- Manual Deploy > Deploy latest commit

V10 changes:
- Website URL only. No paste-text scan.
- Cleaner scoring: one overall score and simple risk drivers.
- Sector and company/context risk are assessed by the tool.
- Compact, readable report.
- Claim-level findings are simplified into concise paragraphs.
- Optional AI refinement via Render environment variable OPENAI_API_KEY.
- Full open-web screening of NGO/government/press sources requires a search API integration and is not performed by this basic hosted version.


V10 Tavily integration:
- Add TAVILY_API_KEY in Render Environment Variables.
- The app will then search external public web sources for NGO, press, regulator/government and legal/context signals.
- No API key should be committed to GitHub.
