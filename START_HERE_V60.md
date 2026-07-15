# Durably v60 — External public-source signals

This repository updates the generic external-signal function used by the website scan.

## Main improvements

- Searches separately for regulator/enforcement, NGO, union/worker, litigation and reputable-media signals.
- Runs both green-claim and social/supply-chain query families, even when few claim themes were detected on the website.
- Combines Tavily and Google Custom Search results when both are configured.
- Ranks sources by authority, issue relevance and company match.
- Correctly excludes company-owned pages without excluding external articles that discuss a company policy or sustainability report.
- Deduplicates repeated coverage of the same event.
- Keeps green and social signals separate.

## Deployment

1. Replace the current GitHub repository files with this package.
2. Commit and push to GitHub.
3. Redeploy on Render.
4. Check `/api/health`; the version must be `hostable_v60_external_signal_recall_precision`.
5. Run a new scan. Old scan results and PDFs do not update automatically.

No new Python dependency is required.
