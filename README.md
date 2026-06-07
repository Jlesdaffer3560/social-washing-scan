# Green & Social Claims Risk Triage - Hostable v33

Professional hostable version of the Green & Social Claims Risk Triage tool.

## What changed in v33

- Clearer **Documents / websites checked** section, listing the specific pages reviewed by the crawler.
- Document/audience assessment is now more concrete and distinguishes consumer-facing material from investor/stakeholder reporting.
- Merged and shortened the previous overlapping score/risk-driver explanations.
- Added a concise **sector exposure** explanation, because some sectors are structurally more exposed to greenwashing or social-washing allegations.
- Added links to the reviewed website/documents in the claim-signal section where available.
- Added clickable external-source links in the green/social source-signal section.
- Added a downloadable `/methodology.pdf` with detailed methodology, references to EU frameworks and international standards, score logic, claim taxonomy and limitations.
- Kept the 2-page client-ready PDF/print report and claim-register CSV export.

## Core scoring model

Each green and social score uses the same high-level model:

- 30% claim wording risk
- 30% substantiation / evidence-gap risk
- 25% external contradictory-context risk
- 15% sector exposure

The global score integrates the green and social scores. Sector exposure is a context factor and should not create a High-risk result on its own.

## Main regulatory lenses

- Green claims: Directive (EU) 2024/825 / EmpCo logic for consumer-facing environmental claims.
- Social claims: social-washing triage, human-rights/labour-rights logic and Regulation (EU) 2024/3015 forced-labour product/supply-chain lens where relevant.

## Deployment

Replace the files in your GitHub repository with the files in this folder, commit to `main`, and push. Render should automatically redeploy if your service is connected to the repository.
