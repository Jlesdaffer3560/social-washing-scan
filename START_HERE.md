# Start here — V64

Read `V64_CHANGELOG.md` and `DEPLOY_V64.txt`. This package contains the complete repository, not only a patch.

# Start here — Durably Sustainability Scan v62

This is the complete GitHub/Render repository. It replaces the existing application files; it is not a separate report plug-in.

## Main changes

- Clearer and more compact **Key sustainability claim signals** with four regulatory/theme sections.
- Repeated claim types are clustered and details are collapsed by default.
- Stronger external-signal precision and structured source/status metadata.
- Data-reliability warning retained on screen and in the PDF.
- Readable two-page company report with a two-page preflight check and no automatic font shrinking.

## Deploy

Copy the complete package to the GitHub repository connected to Render, commit and push. After deployment, verify `/api/health` returns:

`hostable_v62_professional_claim_signals_readable_pdf`

Then perform a new scan and download a new PDF.

See `DEPLOY_V62.txt`, `V62_CHANGELOG.md` and `TEST_RESULTS_V62.txt`.
