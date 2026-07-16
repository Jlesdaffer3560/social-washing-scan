# Start here - Durably v67

This release adds a transparent source register to every scan.

## Main changes

- Full online list of successfully reviewed website pages.
- Separate list of reviewed PDF/documents.
- Separate list of failed fetch attempts.
- Retrieval method and audience classification per source.
- CSV source-register download.
- Compact assessment-coverage section in the two-page PDF.

## Deploy

Push the complete repository to GitHub and redeploy on Render. Verify that `/api/health` returns:

`hostable_v67_scan_coverage_source_register`

Then run a completely new scan.
