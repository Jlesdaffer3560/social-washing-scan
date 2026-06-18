Durably Sustainability Scan v47 replacement package

Replace these files in your GitHub/Render project:
- agent.py
- app.py
- frontend.html
- methodology.pdf

Then commit/push to GitHub and redeploy on Render.

After deployment, check:
https://social-washing-scan-python.onrender.com/api/health

Expected version:
hostable_v47_score_methodology_recalibrated_no_prepub

v47 changes:
- Recalibrated the score methodology to remove the fixed 48/100 plateau.
- Global, Green and Social scores now vary with claim wording, evidence gap, external context, sector/channel sensitivity and regulatory indicators.
- Removed the Pre-publication review section from the UI.
- Updated the methodology PDF with the v47 score calculation.
