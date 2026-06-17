Durably Green & Social Claims Risk Scan - v43 replacement package

Version:
hostable_v43_restored_red_flags_report_downloads_methodology

Files included:
- agent.py: new backend/application file. Replace your old agent.py with this file.
- frontend.html: new professional UI. Replace your old frontend.html with this file.
- methodology.pdf: detailed methodology document served at /methodology.pdf.
- durably_green_social_claims_scan_v43.py: backup/reference copy of agent.py.
- README_INSTALL.txt: this file.

Installation:
1. Make a backup of your current project folder or rename your current agent.py to agent_v42_backup.py.
2. Unzip this package.
3. Copy agent.py, frontend.html and methodology.pdf into the project root, replacing the old files.
4. Commit and push to GitHub if Render deploys from GitHub.
5. Redeploy the Render service.
6. Open the app and check /api/health. The version should be hostable_v43_restored_red_flags_report_downloads_methodology.

Main v43 changes:
- Restored a stronger and clearer Red flags section with grouped red-flag cards.
- Improved Key green and social claim signals.
- Problematic words in detected wording are highlighted in bold/yellow.
- Added visible company report download panel.
- Added direct methodology PDF download link in the introduction and methodology sections.
- Kept the v41/v42 EmpCo and Forced Labour Regulation logic.
