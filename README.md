# Green & Social Claims Risk Assessment

Professional hostable web app for screening company websites and claim-related documents for greenwashing and social-washing risk signals.

## What the tool does

- Reviews green and social claims on company websites and related company pages.
- Separates green claim signals from social claim signals.
- Distinguishes client-facing communication from investor/stakeholder reporting and policy/internal governance documents.
- Assesses green claims through an EmpCo / Directive (EU) 2024/825 lens.
- Assesses social claims through claim wording, evidence gap, external context, sector exposure and, where relevant, Regulation (EU) 2024/3015 on forced-labour products.
- Excludes company-owned documents from the external public-source signals section.
- Provides a concise 2-page PDF report and a downloadable claim register CSV.

## Deploy on Render

Use the included `render.yaml` and deploy as a Python web service.

## Optional external search

The app can use Tavily or Google Custom Search credentials if configured in Render environment variables. If no external search credential is configured, the tool still performs website claim analysis but external public-source signals will be limited.

## Disclaimer

The output is an indicative first-pass assessment only. It is not legal advice and does not establish a legal violation or definitive greenwashing/social-washing finding.
