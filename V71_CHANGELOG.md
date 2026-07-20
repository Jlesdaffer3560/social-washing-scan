# V71 changelog — external-signal recall and precision

Release date: 20 July 2026

## Root cause

The live SHEIN scan performed an external search but retained no external source. Independent sources with clear greenwashing enforcement, forced-labour risk and working-condition findings existed. The provider queries were not sufficiently source-directed, while the final social-polarity gate required extra allegation language even for some unambiguously adverse stakeholder titles.

## Discovery improvements

- Added a generic two-channel search strategy: focused news searches plus source-constrained regulator/stakeholder searches.
- Added domain pools for EU/national regulators, NGOs, unions and investigative media.
- Added provider-level exclusion of reviewed official company domains.
- Added English, Dutch and French controversy query variants.
- Added source controls to Tavily requests (`topic`, `include_domains`, `exclude_domains`) and equivalent Google query constraints.
- Kept the number of provider calls bounded and concurrent.
- The online report now alternates green and social sources and shows up to eight, preventing one dimension from crowding out the other.

## Final-filter improvements

- Clear adverse social titles from recognised independent sources now pass without redundant allegation wording in the snippet.
- Added coverage for plural and multilingual adverse terminology.
- Retained strict entity matching and competitor-primary rejection.
- Retained positive/promotional and exoneration rejection.
- Added explicit detection of company policies, annual/sustainability reports, supplier codes and modern-slavery statements hosted on third-party registers.

## Regression coverage

- European Commission and Reuters green-claim examples.
- Public Eye and Business & Human Rights Resource Centre social examples.
- Company statement hosted on a modern-slavery register.
- Positive worker-wellbeing announcement.
- Competitor-primary article.
- Generic non-SHEIN discovery pipeline and provider-payload controls.
