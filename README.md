# Social Washing Scan Hostable v4

This is a hostable prototype for external feedback testing.

## What works

- Public web UI served from the same Python app.
- Text scan.
- Live URL scan for public webpages.
- Professional report preview.
- Download professional HTML report.
- Print / Save as PDF.
- Text report copy.
- Built-in rule-based analysis.
- Optional OpenAI analysis via `OPENAI_API_KEY`.

## Local test

1. Open a terminal in this folder.
2. Run:

```bash
python app.py
```

3. Open:

```text
http://localhost:8000
```

## Deploy to Render

Render web services host dynamic apps at a public URL and require the app to bind to `0.0.0.0` on the expected port. This app already does that and reads the `PORT` environment variable.

Steps:

1. Create a GitHub repository.
2. Upload these files:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`
3. Go to Render.
4. Create a new Blueprint or Web Service from your GitHub repository.
5. Use:
   - Build command: leave empty
   - Start command: `python app.py`
6. Wait for deployment.
7. Render gives you a public URL like:
   `https://social-washing-scan.onrender.com`

## Optional AI analysis

In Render, add an environment variable:

```text
OPENAI_API_KEY=your_api_key_here
```

Then tick "Use AI analysis if configured" in the UI.

If AI fails or no key is set, the tool automatically uses the rule-based engine.

## Important limitations

- This is a prototype, not a production compliance tool.
- URL scan fetches one page only.
- Some sites block automated scans.
- No database or user accounts yet.
- No authentication yet; anyone with the public URL can use it.
- Do not process confidential information in a public test deployment.
- The output is indicative only and does not replace legal advice, assurance or human rights due diligence.

## Suggested feedback questions for testers

- Is the scan flow clear?
- Are the findings understandable?
- Is the risk score credible?
- Is the report useful for sustainability/legal/marketing teams?
- Which claim categories are missing?
- Should the tool support upload of PDF/Word reports?
- Should the output be more legal, more executive, or more operational?
