# Social Washing Scan Hostable v6

This version fixes the v5 deployment issue by separating the frontend from app.py.

Upload all five files to the ROOT of your GitHub repository:

- app.py
- frontend.html
- requirements.txt
- render.yaml
- README.md

Render settings:
- Runtime: Python
- Build command: pip install -r requirements.txt
- Start command: python app.py

Then use Manual Deploy > Deploy latest commit.
