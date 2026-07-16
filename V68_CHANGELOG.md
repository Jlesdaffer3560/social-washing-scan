# V68 changelog - stability, methodology, privacy and security

## Methodology and wording

- Replaced "Main social-claim lens" for the Forced Labour Regulation with "Main forced-labour and supply-chain assurance lens".
- Rephrased the KU Leuven/HIVA reference as a recurring risk pattern rather than an unsupported claim that it is always the dominant driver.
- Corrected the opening methodology sentence.
- Added Candidate, Retained, Verified and Excluded external-source status definitions.
- Added coverage/confidence and source-analysis status definitions.
- Added an illustrative score example and release date to the methodology PDF.
- Kept the methodology PDF readable and limited to three pages.

## Score consistency

- Frontend score explanations now use the same bands as the backend and methodology:
  - 0-44 Low
  - 45-74 Medium
  - 75-89 High
  - 90-100 Very high

## Source transparency

- Source register now distinguishes:
  - Retrieved and analysed
  - Retrieved and partially analysed
  - Limited text extracted
  - Retrieved but not analysed due to budget
- Added characters analysed, claim-signal count and claim dimensions per source.
- Updated CSV export with the new analysis fields.
- Corrected uploaded internal documents so they appear under Documents / PDFs rather than Website pages.

## Entity safety

- Removed invented `www.<company>.com` fallback for unverified company names.
- Removed automatic `.com` to `.be` substitution after failed access.
- When no official domain is sufficiently verified, users must enter the exact official URL.

## Privacy and interface

- Added a visible upload privacy and retention notice using careful, non-absolute wording.
- Added static build information even when the health call fails.
- Styled both text and URL inputs consistently.
- Added keyboard submission, focus-visible states, ARIA live status and sticky result navigation.

## API and report security

- Added a 12 MB pre-read request-size limit, configurable through `MAX_REQUEST_BYTES`.
- Removed wildcard CORS; same-origin is automatic and optional extra origins use `DURABLY_ALLOWED_ORIGINS`.
- Added configurable in-memory scan/report rate limits.
- Added a bounded concurrent-scan semaphore.
- Replaced sequential `HTTPServer` with `ThreadingHTTPServer`.
- Added HMAC signatures to scan payloads. `/api/report/pdf` rejects unsigned or tampered payloads.
- Optional persistent signing key: `DURABLY_REPORT_SIGNING_KEY`.

## Quality assurance

- Pinned ReportLab and pypdf versions.
- Added `requirements-dev.txt`.
- Added pytest-compatible tests and a GitHub Actions workflow.
- Existing v62-v67 regression scripts continue to pass.
