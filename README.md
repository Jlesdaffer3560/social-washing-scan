# Social Claim Risk Scan Hostable V23

V23 is a corrective update after V21/V22. It restores the fuller V20-style output structure in the frontend and keeps the scoring refinement only.

## Main changes versus V20
- Version updated to `hostable_v23`.
- More conservative and proportionate scoring methodology.
- Evidence credit reduces scores where claims are substantiated.
- Sector/context/external signals are capped modifiers.
- Very High risk is exceptional.
- `.com` to `.be` fallback remains available.

## Files
- `app.py`
- `frontend.html`
- `requirements.txt`
- `render.yaml`
- `README.md`

## Deploy
Upload all files to the root of the GitHub repository, then redeploy on Render.
Check deployment at `/api/health`.
