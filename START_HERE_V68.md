# Start here - Durably v68

## What changed

- Unified frontend score explanations with the published Low / Medium / High / Very high bands.
- Corrected the Forced Labour Regulation description to a forced-labour and supply-chain assurance lens.
- Rephrased the HIVA reference to avoid an unsupported "dominant driver" statement.
- Added persistent build/version information on the homepage.
- Added a transparent privacy notice for uploaded internal documents.
- Replaced automatic guessed-domain and `.be` substitution with a safer exact-URL requirement when official-domain resolution is uncertain.
- Expanded the source register with analysed characters, claim contribution and four analysis statuses.
- Added HMAC-signed PDF payloads, request-size limits, rate limiting, bounded concurrency and `ThreadingHTTPServer`.
- Added keyboard/accessibility improvements, sticky result navigation and correctly styled text inputs.
- Expanded and regenerated the methodology PDF.
- Added real pytest tests and a GitHub Actions workflow.

## Deploy

Push the complete repository to GitHub and redeploy on Render. Verify `/api/health` returns:

`hostable_v68_stability_methodology_privacy_security`

Then run a completely new scan. Old scan payloads cannot generate a v68 PDF because report downloads now require a valid server signature.
