# Durably Sustainability Scan v66

## Claim-card risk-label layout correction

The previous width-only correction was not sufficiently robust. ReportLab may expand a nested title table when a long claim title has a large minimum width. In that situation, a right-aligned `High` or `Very high` label could still cross the right-hand claim-card border.

### Implemented correction

- Removed the risk label from the right-hand edge of the claim-card header.
- Added a fixed-width, colour-coded risk badge on the left of every claim title.
- Added an internal safety gutter to all claim-card header geometry.
- Applied the same structure to the most material finding and all additional material findings.
- Kept the report at exactly two A4 pages without reducing font sizes.

### Regression protection

The v66 test suite now checks:

- `High` and `Very high` with unusually long claim titles;
- all PDF words remain inside the physical page bounds;
- claim-card risk words are located in the left badge zone, away from the right border;
- the generated report remains exactly two pages;
- prior crawler, external-signal and entity-lock tests still pass.

Expected health version:

`hostable_v66_claim_risk_badge_layout_fix`
