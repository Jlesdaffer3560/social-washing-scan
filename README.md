# Social Claim Risk Scan - Hostable V21

This package contains the complete hostable V21 version of the Social Washing Scan.

## Files

- `app.py` - backend and API server
- `frontend.html` - user interface served by `app.py`
- `requirements.txt` - Python dependencies
- `render.yaml` - Render deployment configuration
- `README.md` - instructions
- `__pycache__/` - included only to mirror the previous V20 package structure; it is not required for deployment

## V21 changes

- Calibrated social-washing scoring to avoid overly high risk scores.
- Lower claim-severity scores: High=56, Medium=32, Low=18.
- Evidence-quality credit lowers risk when claims include concrete evidence.
- Reduced sector and external-context modifiers.
- Stricter caps for High and Very High scores.
- Very High risk is reserved for exceptional cases with strong claim, sector and controversy alignment.
- Automatic `.com` to `.be` fallback when the original `.com` website is not accessible.

## Render deployment

Render must see these files in the root of the GitHub repository:

- app.py
- frontend.html
- requirements.txt
- render.yaml
- README.md

Do not upload only the zip file to GitHub. Extract the zip first, open the folder, and upload the individual files to the repository root.

Render start command:

```bash
python app.py
```

Health check:

```text
/api/health
```

Expected version response:

```text
hostable_v21
```
