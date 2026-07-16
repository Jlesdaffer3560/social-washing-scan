# V63 — External public-source signal recall and diagnostics

## Problem corrected

The external-search layer could return no retained signal for companies with well-documented regulator, NGO, union or investigative-media controversies. The main causes were:

- long multi-term queries that reduced search recall;
- exact singular/plural matching (`wage` but not `wages`, or `worker rights` but not related variants);
- insufficient recognition of phrases such as illegal working hours, piecework wages and labour exploitation;
- no stakeholder-domain fallback when the first queries returned no or too few retained signals;
- an ownership test that could classify an independent hostname as company-owned merely because it contained the brand name;
- no visible diagnostics explaining whether failure occurred at search, company matching or negative-signal filtering.

## V63 changes

1. **Short, high-recall primary queries**
   - Separate simple searches for greenwashing, environmental-claim enforcement, forced labour, working conditions, wages, labour rights and child labour.

2. **Second-pass stakeholder searches**
   - When fewer than two signals survive, the engine runs targeted searches across regulator, NGO and reputable-media domains.
   - The logic is generic and uses the scanned company name; no company-specific signal is hard-coded.

3. **Improved negative-language detection**
   - Handles singular/plural and common wording variants.
   - Recognises illegal/excessive working hours, low or piecework wages, labour exploitation, rights risks, vague/omissive green claims and similar controversy wording.

4. **Safer company-owned filtering**
   - When the official website is known, ownership is determined by the registrable official domain.
   - Independent campaign, watchdog or stakeholder domains are no longer removed solely because the company name appears in their hostname.

5. **Search diagnostics**
   - Every green and social external-search layer now reports:
     - raw results;
     - company matches;
     - negative candidates;
     - retained signals;
     - whether fallback stakeholder searches were used;
     - providers and queries used.
   - These diagnostics are displayed in the web interface.

6. **Precision safeguards retained**
   - Company-owned sources remain excluded.
   - Positive or neutral announcements remain excluded.
   - Entity matching, external ownership, negative polarity and dimension relevance must all pass.
   - Retained signals still require manual verification.

## Expected SHEIN benchmark

The generic logic is now capable of retaining, when returned by the configured search provider, examples such as:

- official regulatory enforcement concerning misleading environmental claims;
- NGO investigations concerning illegal working hours and wages;
- labour-rights reports concerning suppliers and working conditions.

These are test benchmarks only. Search results are not hard-coded into production output.
