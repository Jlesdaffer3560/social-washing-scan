# Durably v65 - Generic entity lock and PDF layout fix

## Scope

This release verifies that the v64 entity protections are applied generically, not only to SHEIN, and fixes the two-page PDF claim-card overflow where risk labels such as `High` could render outside the right border.

## Generic entity corrections

- Company identity is anchored to the user's exact input and the reviewed official domain for every company.
- Official-domain resolution now requires an exact registrable-domain label or strong title/content evidence. Arbitrary hostname substring matches are no longer accepted.
- Company-owned source detection uses exact official roots and corporate suffixes. A watchdog domain such as `brandwatch.org` is not treated as company-owned merely because the brand name appears in the hostname.
- External sources are automatically retained when the target is present in the title or URL. Body-only matches require the target to be prominent, repeated at least three times and directly linked to controversy language.
- This body-only rule is generic and prevents articles primarily about a competitor from leaking into another company's results without relying on a fixed competitor list.
- When primary-site coverage is limited, the crawler can conservatively discover an additional official sustainability/group site for any company, provided a search provider is configured.
- Existing verified parent/group-domain mappings remain only as optional high-confidence overrides; the core protection no longer depends on SHEIN-specific rules.

## PDF layout corrections

- Every nested table in a claim card now uses the true inner card width after padding.
- The risk-label column has a fixed internal width and wraps safely for `High` and `Very high`.
- The Why it matters / Evidence gap grid no longer exceeds its parent cell.
- Score cards now account for outer-table gutters and cell padding.
- Two-column external-signal cards now account for the centre gutter.
- PDF preflight still requires exactly two pages and does not shrink fonts to make content fit.

## Version

`hostable_v65_generic_entity_lock_pdf_layout_fix`
