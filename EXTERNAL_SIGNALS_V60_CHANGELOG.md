# V60 — External public-source signal improvements

## Corrected issues

- Expanded external searches from a maximum of three narrow queries to a balanced set of regulator, NGO, union, litigation, investigative-media and claim-specific queries.
- Combined configured search providers instead of stopping after the first provider returned any result.
- Replaced snippet-only stakeholder detection with source-domain classification for regulators, NGOs, unions and reputable media.
- Corrected the company-owned-source filter. An external article is no longer excluded merely because it discusses a company sustainability report, policy or supplier code.
- Added source ranking by authority, negative-signal specificity, company relevance and provider relevance.
- Added URL and event-level de-duplication so multiple articles about one case do not appear as separate independent controversies.
- Retained strict exclusion of company-owned sources and positive/neutral corporate news.

## Render settings

Optional environment variables:

- `EXTERNAL_SIGNAL_MAX_QUERIES` — default 6, allowed 4–8.
- `EXTERNAL_SIGNAL_RESULTS_PER_QUERY` — default 6, allowed 4–10.
- `EXTERNAL_SIGNAL_WORKERS` — default 4.
- `EXTERNAL_SEARCH_ALL_PROVIDERS` — default 1. Set to 0 to return to primary/fallback behaviour.

The existing `TAVILY_API_KEY` and optional Google Custom Search settings remain unchanged.
