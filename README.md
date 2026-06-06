# Social Washing Risk Triage — Hostable V26

Upload these files to the root of your GitHub repository:

- `app.py`
- `frontend.html`
- `requirements.txt`
- `render.yaml`
- `README.md`

Render settings:

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`

Optional environment variables for external search:

- `TAVILY_API_KEY`
- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_CX`

After deployment, click **Check backend**. It should show version `hostable_v26_social_washing_triage_frontend_bugfix`.

## V26 changes

### 1. Frontend scan bug / usability fix

The scan button is now bound through explicit JavaScript event listeners instead of relying on inline click handling only. The interface also disables buttons while the scan is running and shows clear progress/error messages.

### 2. Better opening page

The landing page now explains:

- what the tool is for;
- what social-washing triage means;
- what the four score components are;
- how to interpret the result;
- why some websites may fail because they block automated crawlers.

### 3. More visible status messages

The old small status line has been replaced by a prominent status box with:

- backend status;
- running status;
- timeout/error explanation;
- practical hints for the user.

### 4. Faster and less fragile scan behavior

The backend now uses shorter network timeouts and fewer crawler/external-search calls to reduce the risk that Render appears to hang:

- main website page timeout reduced;
- internal page crawl reduced to the top 3 relevant pages;
- claim-specific external queries reduced to the top 5 themes;
- public-source provider timeout reduced.

## Methodology retained from V25

The scan treats social washing as a triage signal based on three core elements:

1. a social, human-rights, labour, customer, community or supplier claim;
2. a substantiation / evidence gap;
3. relevant external contradictory context.

Sector sensitivity is only a modifier. It cannot create a High risk result by itself.

The integrated score remains:

- 30% claim wording risk;
- 30% substantiation / evidence-gap risk;
- 25% external contradictory-context risk;
- 15% sector sensitivity.

## Important limitation

This is an indicative first-pass triage tool. It is not legal advice and does not establish that social washing occurred. External public-source signals must be manually verified.
