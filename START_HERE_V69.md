# Start here - Durably v69

## Deploy

1. Extract `Durably_v69_Report_Token_and_Strict_Negative_External_Signals.zip`.
2. Replace the complete contents of the GitHub repository with the extracted files.
3. Commit and push all files.
4. Let Render complete the new deployment.
5. Open `/api/health` and confirm:

   `hostable_v69_report_token_strict_negative_external_signals`

6. Run a completely new company scan.
7. Download the two-page report from that new result.

Old v68 results do not contain the new `_report_token` and should not be used to test the v69 PDF workflow.

## Strongly recommended Render secret

Set a long random value for:

`DURABLY_REPORT_SIGNING_KEY`

V69 remains operational without it because it has a deterministic fallback, but a private secret provides materially stronger integrity protection.

Optional token lifetime setting:

`REPORT_TOKEN_MAX_AGE_SECONDS=21600`

The default is six hours.

## External-signals validation

Test at least:

- a company with known regulator or NGO controversy;
- a company with recent positive sustainability announcements;
- an article primarily about a competitor;
- a source reporting that allegations were dismissed or that no evidence was found.

Only directly matched negative external stakeholder sources should appear. Positive announcements, achievements, awards, partnerships and exoneration articles must not be shown.
