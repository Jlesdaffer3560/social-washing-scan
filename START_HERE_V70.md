# Start here — Durably Sustainability Scan v70

This release is ready for deployment after the existing environment variables have been checked.

1. Deploy the complete package without changing `render.yaml`.
2. Confirm that `/api/health` returns release `v70` and version `hostable_v70_report_readability_external_source_precision`.
3. Run a Puratos scan and verify that Puratos policy or brand-domain pages do not appear under **External public-source signals**.
4. Confirm that independent adverse sources, when found, still require human verification.
5. Generate a company PDF once after deployment to confirm the existing signed report-token flow.

The scan remains an indicative first-pass claims review, not legal advice or a legal finding.
