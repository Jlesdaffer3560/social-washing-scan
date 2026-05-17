# Social Washing Scan Hostable v5

Improved structured prototype with more professional report output.

## Main changes versus v4

- Claim-level findings are now displayed as structured assessment cards.
- Each finding includes:
  - detected issue
  - risk rationale
  - evidence gap
  - recommended correction
  - suggested revised wording
  - narrative assessment
- Text report preview is now more report-like and less data-like.
- Professional HTML report has a clearer structure.
- Same simple Render deployment structure as before.

## Deploy on Render

Replace these files in the root of your GitHub repository:

- app.py
- requirements.txt
- render.yaml
- README.md

Then in Render:

- Runtime: Python
- Build command: pip install -r requirements.txt
- Start command: python app.py

Then use Manual Deploy > Deploy latest commit.

## Optional AI

Set environment variable in Render:

OPENAI_API_KEY=your_key

If no API key is set, the structured rule-based engine is used.
