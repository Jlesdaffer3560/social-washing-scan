Durably Sustainability Scan - replacement files

Replace the following files in your GitHub / Render project folder:

1. agent.py
2. app.py
3. frontend.html
4. methodology.pdf

Then commit, push to GitHub and redeploy on Render.

After deployment, check:
https://social-washing-scan-python.onrender.com/api/health

The version should show:
hostable_v51_contextual_claim_scoring

Main improvements:
- Contextual claim selection: neutral supplier references such as "backing British suppliers" are no longer treated as supplier-responsibility claims merely because the word "suppliers" appears.
- Supplier claims are retained when the surrounding wording implies responsibility, traceability, certification, audits, human-rights/labour controls, all-supplier coverage, due diligence or forced-labour assurance.
- External signals are filtered more strictly to retain negative external stakeholder perceptions only.
- Methodology document updated with clearer score-calculation explanation and claim-selection logic.
