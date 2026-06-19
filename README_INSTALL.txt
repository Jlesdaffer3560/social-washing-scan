Durably Sustainability Scan - replacement files

Replace the existing files in your GitHub/Render project with these files:

- agent.py
- app.py
- frontend.html
- methodology.pdf

Then commit/push to GitHub and redeploy on Render.

After deployment, check:
https://social-washing-scan-python.onrender.com/api/health

Expected backend version:
hostable_v52_material_claims_recalibrated_scoring

Main change:
The claims analysis now retains only material problematic claim signals. Neutral supplier references, general sustainability context and positive/neutral statements are not shown or scored unless they contain direct EmpCo indicators or high-sensitivity social assurance wording.
