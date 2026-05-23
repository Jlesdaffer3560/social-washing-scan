# Social Claim Risk Scan - Hostable V21

This package contains the hostable V21 version of the Social Washing / Social Claim Risk Scan.

## Main V21 updates

- Version updated to `hostable_v21`.
- More conservative scoring, calibrated against the Durably SocialCheck benchmark.
- Lower claim-severity scores: High = 56, Medium = 32, Low = 18.
- Evidence-quality credit reduces risk where claims are supported by scope, metrics, targets, due diligence, grievance/remedy or verification signals.
- Sector, context and external controversy modifiers are capped to avoid inflated scores.
- Very High risk is exceptional and requires high-risk sector + multiple high-risk claims + strong external relevance.
- Automatic `.com` to `.be` fallback: when a `.com` website is inaccessible, the scan retries the equivalent `.be` domain and reports this in `fallback_note`.

## Files

- `app.py` - main web application.
- `frontend.html` - user interface served by the app.
- `requirements.txt` - dependency file for deployment.
- `render.yaml` - optional Render deployment configuration.

## Render deployment

1. Upload or commit these files to the GitHub repository used by Render.
2. Ensure `app.py` is at the root of the repository.
3. In Render, use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python app.py`
4. Redeploy the service.
5. Open the app URL and check that the page reports version `hostable_v21`.

## Optional environment variables

- `TAVILY_API_KEY` - used when available for external research.
- `OPENAI_API_KEY` - reserved for AI-supported logic when configured.
