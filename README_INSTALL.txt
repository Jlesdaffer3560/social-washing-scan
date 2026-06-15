Durably Green & Social Claims Risk Scan - v42 replacement package

Files included:
- agent.py: updated backend with APP_VERSION = hostable_v42_professional_ui_consistency_check
- frontend.html: updated professional UI; hides empty result sections before a scan, improves wording, structure and report rendering
- durably_green_social_claims_scan_v42.py: backup copy of the same backend

Installation:
1. Make a backup of your current project folder.
2. Unzip this package.
3. Copy agent.py and frontend.html into your Render/GitHub project folder.
4. Replace the existing files with the same names.
5. Commit and push to GitHub if Render deploys from GitHub.
6. Redeploy on Render.
7. Open /api/health or check the page header. The backend should show v42.

Do not upload the zip file itself to Render as the running application. Unzip it first and replace the old files.
