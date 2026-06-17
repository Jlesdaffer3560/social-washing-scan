Durably Green & Social Claims Risk Scan - v44 replacement package

Version: hostable_v44_detailed_methodology_two_page_report_claim_sources

Replace these files in your GitHub/Render project:
1. agent.py
2. frontend.html
3. methodology.pdf

Recommended steps:
1. Backup your current project folder or at least rename your old agent.py and frontend.html.
2. Unzip this package.
3. Copy agent.py, frontend.html and methodology.pdf into the project root, replacing the old files.
4. Commit and push to GitHub.
5. Re-deploy on Render.
6. Open /api/health and verify that the version is:
   hostable_v44_detailed_methodology_two_page_report_claim_sources

Main v44 improvements:
- detailed methodology PDF with EU regulatory references and score calculation method;
- executive summary with clearer Global, Green and Social scores;
- restored professional red-flag structure, now separated into green-claim and social-claim red flags;
- claim-signal table now shows source page/document/link where the claim was found;
- problematic trigger words are highlighted and shown separately;
- visual/icon cue detection from available HTML attributes such as alt, title, class, id and src;
- improved external public-source query recall and brand aliases, including Inditex/Zara;
- clearer 2-page PDF company report generation via browser print / Save as PDF;
- removed redundant Text Report section from the UI.

Note:
External public-source signals require Tavily or Google Custom Search credentials in Render environment variables.
