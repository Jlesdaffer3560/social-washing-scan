# Social Washing Risk Triage — Hostable V25

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

After deployment, click **Check backend**. It should show version `hostable_v25_social_washing_triage`.

## V25 improvements

### 1. Stricter social-washing methodology

The scan now treats social washing as a triage signal based on three core elements:

1. a social, human-rights, labour, customer, community or supplier claim;
2. a substantiation / evidence gap;
3. relevant external contradictory context.

Sector sensitivity is only a modifier. It cannot create a High risk result by itself.

### 2. New scoring model

The integrated score is now calculated as:

- 30% claim wording risk;
- 30% substantiation / evidence-gap risk;
- 25% external contradictory-context risk;
- 15% sector sensitivity.

High risk requires a broad or sensitive claim, insufficient substantiation and relevant external contradiction.

### 3. Corrected evidence-gap logic

Evidence credit is now calculated only from the original crawled website text. The tool no longer gives evidence credit for words appearing in its own generated recommendations.

### 4. Claim-specific external search

External search queries are now derived from detected claim themes. For example:

- supplier claims trigger searches on supplier labour rights, forced labour, audit failure and remediation;
- diversity claims trigger searches on discrimination, pay gap and inclusion controversies;
- customer/accessibility claims trigger searches on customer-protection and vulnerable-customer complaints.

### 5. Clearer output structure

The frontend now shows:

1. executive summary;
2. four-part score composition;
3. risk driver table;
4. key social-washing signals;
5. external public-source signals;
6. recommended actions;
7. methodology and limitations.

### 6. Social-washing taxonomy

Detected claims are mapped to clearer categories such as:

- supplier responsibility washing;
- diversity or inclusion washing;
- human-rights or labour-rights washing;
- worker welfare washing;
- customer fairness or accessibility washing;
- community or social-impact washing;
- overstatement / absolute-claim risk.

## Important limitation

This is an indicative first-pass triage tool. It is not legal advice and does not establish that social washing occurred. External public-source signals must be manually verified.
