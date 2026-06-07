# Green & Social Claims Risk Triage — Hostable v29

This version expands the previous Social Washing Risk Triage into a combined **Green & Social Claims Scan**.

## What changed in v29

- Adds a dedicated **green-claims module** based on the logic of the EU Empowering Consumers for the Green Transition Directive, **Directive (EU) 2024/825 / EmpCo**.
- Keeps the existing social-claims methodology and adds a dedicated **Forced Labour Regulation lens** for the social module, based on **Regulation (EU) 2024/3015**.
- Produces three scores:
  - **Global green + social claims risk score**
  - **Green risk score**
  - **Social risk score**
- Adds a document/audience classification:
  - **Consumer-facing / commercial communication**
  - **Investor / stakeholder report**
  - **Mixed or unclear**
- Treats EmpCo relevance as strongest for B2C/consumer-facing material such as websites, product pages, marketing pages, folders and brochures.
- Treats annual reports, ESG reports and sustainability reports mainly as evidence sources, unless the same claims are reused in consumer-facing communications.

## Green-claims methodology

The green module uses the same triage logic as the social module:

- 30% claim wording risk
- 30% substantiation / evidence-gap risk
- 25% external contradictory-context risk
- 15% sector sensitivity

The module looks for EmpCo-relevant green-claim risk areas, including:

- generic environmental claims such as “green”, “sustainable” or “environmentally friendly”;
- climate-neutrality, net-zero and offsetting claims;
- circularity, durability, recyclability and repairability claims;
- comparative environmental claims;
- sustainability labels and certification claims;
- future environmental-performance claims;
- absolute or purity wording such as “zero impact”, “100% sustainable” or “chemical-free”.

## Social-claims methodology

The social module continues to assess:

- claim wording risk;
- substantiation gaps;
- relevant contradictory public-source signals;
- sector sensitivity.

It covers supplier responsibility, labour rights, human rights, diversity and inclusion, worker welfare, customer fairness/accessibility and community/social-impact claims.

### Forced Labour Regulation lens

The social module now also detects and assesses forced-labour/product-market claim areas, including:

- “forced labour free” or “forced labor free” wording;
- modern-slavery-free supply-chain claims;
- product or supplier traceability claims;
- import/export control wording;
- responsible-sourcing claims that imply forced-labour risk control.

Where those signals are detected, the scan asks for evidence such as product/supplier traceability, forced-labour risk assessment by product/geography, grievance and remediation processes, mitigation/escalation steps and withdrawal/customs response readiness under Regulation (EU) 2024/3015.

## How to deploy on Render

1. Upload/replace the project files in your GitHub repository:
   - `app.py`
   - `frontend.html`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`
2. Commit the changes.
3. Wait for Render to redeploy automatically.
4. Open the app URL.
5. Click **Check backend**.
6. Run a test scan with a company website or a specific sustainability/product page.

## Important limitation

This is an indicative first-pass triage tool. It is not legal advice and does not determine that greenwashing or social washing has occurred. The Forced Labour Regulation module is an indicative social-claims/product-market risk lens, not a legal compliance assessment. External search results are signals for manual review.


## v28 update

- Merged the former separate “Score composition” and “Risk driver table” sections into one integrated “Score composition and risk drivers” section.
- The combined section now shows green/social score components and qualitative explanations in one place to reduce repetition.


## v29 update

- Integrated the EU Forced Labour Regulation — Regulation (EU) 2024/3015 into the social-claims module.
- Added forced-labour-specific claim detection, evidence requirements, public-source search themes, red flags and recommended actions.
- Added a specific frontend explanation of the forced-labour lens.
