# Social Claim Risk Scan Hostable V11

Upload these five files to the ROOT of your GitHub repository:

- app.py
- frontend.html
- requirements.txt
- render.yaml
- README.md

Render:
- Runtime: Python
- Build command: pip install -r requirements.txt
- Start command: python app.py

Environment variable for external search:
- TAVILY_API_KEY

After deployment, click Check backend. It should show:
Backend OK. Version: hostable_v11. AI configured: false. Tavily configured: true
