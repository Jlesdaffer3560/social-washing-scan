# Social Claim Risk Scan - hostable_v22

This package keeps the same layout and structure as the previous hostable version, while refining only the scoring methodology.

## V22 changes

- App version: `hostable_v22`
- Keeps the frontend flow and output structure unchanged, except for version labels.
- Refines the scoring logic to avoid inflated risk scores.
- Claim wording remains the anchor of the score.
- Sector, context and external-source signals are capped modifiers.
- Evidence-quality credit lowers the score where claims are supported by policy, scope, KPIs, targets, due diligence, grievance/remedy or verification signals.
- Very High is reserved for exceptional cases with strong alignment between high-risk claims, high-risk sector and relevant external controversy/context.
- The `.com` to `.be` fallback remains available when the original `.com` website is inaccessible.

## Files

- `app.py`
- `frontend.html`
- `requirements.txt`
- `render.yaml`
- `README.md`
- `__pycache__/`

## Deployment

Upload the files to the root of the GitHub repository used by Render. Render must see `app.py`, `frontend.html`, `requirements.txt` and `render.yaml` directly in the repository root.

After deployment, verify the active version at:

`/api/health`

Expected version: `hostable_v22`.
