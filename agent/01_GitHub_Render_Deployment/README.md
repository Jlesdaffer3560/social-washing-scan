# Durably two-page company report v2

This package adds the revised company-report layout to the existing Flask application.

## Files

- `company_report_v2.py` — complete drop-in module, including the HTML/CSS template.
- `example_report_data.json` — test payload based on the Puratos report.
- `integration_example.py` — minimal integration examples.
- `generated_demo.html` — generated report for local visual testing.
- `generated_demo.pdf` — reference PDF generated from the module.

## 1. Copy the module

Copy `company_report_v2.py` to the root of the existing application, next to `app.py`
or the main Flask module.

## 2. Register the route

Add this after the Flask app has been created:

```python
from company_report_v2 import register_company_report_v2

register_company_report_v2(
    app,
    report_provider=lambda: session.get("last_scan_result"),
)
```

Replace `session.get("last_scan_result")` with the variable or function that returns the
most recent scan-result dictionary in the current application.

The route is then:

```text
/company-report-v2
/company-report-v2?print=1
```

The second URL opens the browser print dialog automatically.

## 3. Connect the existing report button

Example JavaScript:

```javascript
window.open("/company-report-v2?print=1", "_blank");
```

When the current result exists only in JavaScript, send it as JSON:

```javascript
async function openCompanyReportV2(scanResult) {
  const response = await fetch("/company-report-v2", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(scanResult)
  });
  const html = await response.text();
  const reportWindow = window.open("", "_blank");
  reportWindow.document.open();
  reportWindow.document.write(html);
  reportWindow.document.close();
}
```

## 4. Data compatibility

`normalise_report_data()` accepts several common key variants, including:

- `company`, `company_name`, `entity_name`
- `global_score`, `overall_score`, `scores.global`
- `green_score`, `scores.green`
- `social_score`, `scores.social`
- `top_findings`, `priority_findings`, `findings`, `risk_drivers`
- `priority_actions`, `recommended_actions`, `actions`
- `sources_reviewed`, `reviewed_sources`, `coverage.sources`

For a guaranteed result, map the existing result to the structure in
`example_report_data.json`.

## 5. Render deployment

No extra dependency is required if Flask and Jinja are already present.
Commit the new module and the small integration change, push to GitHub and trigger a
Render deployment.

## Important

The template intentionally limits the report to:

- three priority findings;
- three priority actions;
- two external signals;
- four reviewed sources.

Long fields are shortened to keep the output within exactly two A4 pages.
