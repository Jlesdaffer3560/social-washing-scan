# Durably Sustainability Scan v69

## Purpose

V69 fixes two production regressions found after the v68 deployment:

1. the two-page company report could not be downloaded because the browser-posted scan payload failed the server signature check;
2. positive or neutral articles could still appear under **External public-source signals**, although this section is intended exclusively for negative external stakeholder context.

Expected health version:

`hostable_v69_report_token_strict_negative_external_signals`

## 1. Robust two-page PDF download

### Root cause

V68 signed the complete Python scan-result JSON and then expected the browser to post an identical object back. A browser JSON parse/stringify round-trip can change the textual representation of numbers and other JSON details, even when the underlying data is equivalent. Because the HMAC was calculated over the exact serialized text, an equivalent browser payload could fail verification.

The optional signing key also defaulted to a random process key when `DURABLY_REPORT_SIGNING_KEY` was not configured. A Render worker restart could therefore invalidate a previously issued signature.

### V69 correction

- A scan response now contains an opaque `_report_token`.
- The token contains the exact server-side scan payload in compressed form.
- The browser sends only `{ "report_token": "..." }` to `/api/report/pdf`.
- The backend verifies and decodes the token before generating the PDF.
- The browser no longer has to reproduce Python's JSON number formatting or object serialization.
- The token expires after six hours by default; configure `REPORT_TOKEN_MAX_AGE_SECONDS` to change this.
- A configured `DURABLY_REPORT_SIGNING_KEY` remains strongly recommended.
- When that environment variable is absent, a deterministic application fallback prevents report downloads from breaking after a worker restart. This fallback protects against accidental modification but is not a substitute for a private production secret.
- The old whole-payload signature remains available for one-release backward compatibility.

## 2. External signals restricted to negative news

### Root cause

The previous external-search ranker first retained entity-relevant and sustainability-relevant results. Negative-polarity checks were applied later. Positive articles containing terms such as sustainability, carbon neutral, workers, investigation or report could therefore survive parts of the pipeline and appear in some output paths.

### V69 correction

A source must now pass the negative-polarity gate **before it enters the retained result set**.

The generic classifier:

- requires a relevant environmental or social controversy anchor;
- requires an explicit adverse issue, negative headline, multiple adverse markers, or formal regulator/legal action;
- rejects achievement, award, partnership, certification, milestone, launch and progress headlines unless they also clearly report an adverse event;
- rejects exoneration or dismissal headlines such as “cleared of”, “no evidence of”, “complaint dismissed” or “investigation closed without action”;
- continues to exclude company-owned sources and competitor-primary articles;
- labels every retained compact source with `polarity: negative` and a polarity reason.

The restriction is enforced at three levels:

1. backend search ranking and retention;
2. frontend rendering;
3. two-page PDF generation.

This means positive or neutral results cannot re-enter the visible external-signals section through a secondary output path.

## 3. User-interface changes

- The external-signals introduction now states that only explicitly negative external stakeholder sources are shown.
- Positive achievements, awards, partnerships, neutral company coverage and company-owned evidence are explicitly described as excluded.
- The PDF download sends the opaque report token rather than the complete mutable scan result.
- PDF errors are parsed and displayed as a clean message.
- A failed new scan clears the previous scan result, preventing accidental download of stale data.

## 4. Two-page report

- The report independently filters external signals to `polarity: negative`.
- Its section note now states that positive, neutral and company-owned sources are excluded.
- The existing readable two-page layout and claim-risk badge geometry are unchanged.

## 5. Tests

V69 adds tests for:

- report-token creation and decoding;
- browser-style JSON round-trip survival;
- token tampering rejection;
- successful PDF generation through the live HTTP endpoint using a report token;
- exclusion of positive green and social articles;
- exclusion of exoneration headlines;
- retention of regulator enforcement and worker-rights controversy articles;
- confirmation that the retained external result set contains only negative-polarity sources;
- all previous v62-v68 crawler, entity, claim, source-register and PDF regressions.
