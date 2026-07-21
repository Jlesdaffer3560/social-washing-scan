# V72 changelog — prohibited vs. problematic legal-basis classification

Release date: 21 July 2026

## What changed

Every retained claim (green and social) is now classified into exactly one of two
legal-basis categories, distinct from claim risk (High/Medium/Low) and from claim
subject matter (EmpCo environmental / social characteristics / forced labour):

- **Prohibited if unsubstantiated (EmpCo Annex I)** — the claim wording matches one
  of the fixed, per-se-unfair practices in EmpCo Annex I: self-declared sustainability
  labels without independent certification (2a), unspecified generic environmental
  claims (4a), aggregate/whole-product benefit claims based on only one aspect (4b),
  product-level climate-neutral/reduced/positive claims based on offsetting (4c), and
  legal compliance presented as a distinctive feature (10a). Once EmpCo applies
  (27 September 2026), these are automatically unfair if the described conditions are
  met — no individual balancing test is needed.

- **Problematic, not automatically prohibited (case-by-case)** — the claim is not on
  that fixed list, but can still be found misleading after an individual assessment
  under general UCPD rules (Article 6 misleading actions, Article 7 omissions, or
  Article 6(2)(d) for future claims). This covers all social/human-rights/labour
  claims, forced-labour readiness wording, absolute and comparative overstatements,
  and future environmental-performance claims.

## Backend (app.py)

- Added `classify_legal_basis(f)`. Reads the existing `blacklisted_practice_indicator`
  flag and returns `legal_basis_category` ('prohibited' / 'problematic'),
  `legal_basis_label` and a one-paragraph `legal_basis_short` explanation.
- Wired into `enrich_green_finding` (unchanged detection logic, only adds the new
  fields) and into `enrich_social_finding` (explicitly sets
  `blacklisted_practice_indicator=False`, since no social/human-rights characteristic
  currently has a fixed Annex I blacklist entry — matches the case-by-case treatment
  already described in `social_blacklisted_indicator`'s existing text).
- `build_regulatory_risk_summary` now returns a `legal_basis_breakdown` object:
  prohibited/problematic counts, both labels, a plain-language explanation of the
  distinction, and up to 5 example claims per category.
- Bumped `APP_VERSION` / `APP_RELEASE_LABEL` to v72.

## Dashboard (frontend.html)

- Each claim card now shows a second badge next to the existing topic badge: a red
  "Prohibited (Annex I)" badge or an amber "Problematic (case-by-case)" badge
  (hover/tap shows the full explanation via the `title` attribute).
- The claim detail view has a new "Legal basis" box alongside "Why it matters" and
  "Evidence required".
- A new summary block sits at the top of the claims section, above the existing
  four-metric overview: two stat tiles (Prohibited count / Problematic count) plus a
  short, always-visible explanation of what the distinction means and why it matters
  (EmpCo Annex I fixed list vs. UCPD Art. 6/7 case-by-case test).

## Regression coverage

- All 25 existing pytest cases across test_v68 through test_v71 pass unchanged
  (2 hard-coded version-string assertions updated from v71 to v72, no logic changes
  to those tests).
- 3 script-based tests (v66 badge layout, v67 scan coverage, v68 stability) pass
  unchanged.
- Manually verified classification output against sample text for all seven green
  claim types (generic/offsetting/label/legal-requirement → prohibited; absolute/
  comparative/future → problematic) and both social claim types (forced-labour,
  human-rights → problematic).
- Manually rendered the updated dashboard HTML/CSS to confirm the new badges and
  summary block display correctly.

## Rollback

Redeploy v71. No migration or data change is required — `legal_basis_category` is
computed at scan time from existing fields, nothing is persisted.
