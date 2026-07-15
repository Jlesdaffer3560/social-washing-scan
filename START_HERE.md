# Durably Sustainability Scan — Complete Company Report v2 Package

This package contains everything created for the revised two-page company claim-risk report.

## Folder 01 — GitHub and Render deployment

- `company_report_v2.py`  
  Drop-in Flask report module. It contains the complete two-page HTML/CSS template,
  data normalisation and the Flask route.

- `integration_example.py`  
  Minimal code example showing how to register the report route in the current Flask app.

- `example_report_data.json`  
  Test payload based on the Puratos example.

- `README.md`  
  Detailed installation and deployment instructions.

## Folder 02 — Examples and previews

- `generated_demo.pdf`  
  Reference PDF generated with the new module.

- `generated_demo.html`  
  Browser version of the same report.

- `page-1.png` and `page-2.png`  
  Quick visual previews.

## Folder 03 — Design reference

- `durably_company_report_layout_v2.pdf`  
  The redesigned two-page visual concept.

- `durably_company_report_layout_v2_template.html`  
  Standalone HTML/CSS reference template.

## Fast integration

1. Copy `01_GitHub_Render_Deployment/company_report_v2.py` into the root of the
   existing Flask project.
2. Add the registration code from `integration_example.py` after the Flask app
   has been created.
3. Connect the current report button to `/company-report-v2?print=1`.
4. Commit the changes to GitHub.
5. Trigger a Render deployment.
6. Test the output with the included `example_report_data.json`.

The module limits content automatically so that the generated report remains
within exactly two A4 pages.
