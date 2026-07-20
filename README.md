# Durably Sustainability Scan - v71

V71 improves the recall of genuinely negative external stakeholder sources without weakening the v69/v70 false-positive protections.

Expected health version:

`hostable_v71_external_signal_recall_precision`

Read `START_HERE_V71.md`, `V71_CHANGELOG.md`, `DEPLOY_V71.txt` and `TEST_RESULTS_V71.txt` before deployment.

## Main v71 changes

- Combines focused news searches with regulator-, NGO-, union- and investigative-media domain searches.
- Excludes reviewed company domains at provider-query level, before ranking.
- Uses dedicated green and social query strategies, including English, Dutch and French search terms.
- Recognises clear adverse social headlines and stakeholder findings that v70 could reject too aggressively.
- Continues to exclude positive/neutral coverage, competitor-primary articles and company-authored policies or reports.
- Excludes company statements even when they are hosted on a public modern-slavery register.
- Keeps independent adverse sources visible with direct entity matching, source URL and manual-verification status.
- Retains all v70 readability, layout, source-precision and signed-PDF improvements.

The scan is an indicative first-pass assessment. It is not legal advice and does not establish a breach of EmpCo, the Forced Labour Regulation or any other law.
