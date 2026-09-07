"""Offline regression tests for v62. Run: python test_v62.py"""
import importlib.util
import io
import json
import sys
import urllib.request
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

app = load("app_v62", ROOT / "app.py")
report = load("report_v62", ROOT / "report_pdf.py")
# Loading app.py under a separate module name ("app_v62", shadowed here by the local `app`
# variable above) re-runs its module-level urllib.request.install_opener(_SAFE_OPENER) with a
# NEW opener object, silently replacing the process-wide opener the CANONICAL `app` module (if
# already imported elsewhere in the same pytest session, under sys.modules['app']) installed --
# e.g. breaking test_v68_pytest.py's test_ssrf_redirect_guard_is_actually_wired_into_used_requests,
# which checks urllib.request._opener is app._SAFE_OPENER. Restore the canonical module's opener
# (if it's already loaded) so this file's own module reload doesn't leak into later test files.
if 'app' in sys.modules and hasattr(sys.modules['app'],'_SAFE_OPENER'):
    urllib.request.install_opener(sys.modules['app']._SAFE_OPENER)

# Dropped the APP_VERSION pin: it only ever recorded what version existed when this test was
# last touched (already drifted once, from v62 to v72, and now far past that too), not
# anything about the logic actually exercised below -- it goes stale on every release.
assert app.APP_VERSION

positive = {
    "title": "Company achieves carbon-neutral operations",
    "url": "https://news.example/article",
    "content": "The company announced a sustainability milestone. Banner featuring a learn more button.",
}
negative = {
    "title": "Regulator investigates company over misleading environmental claims",
    "url": "https://regulator.example.gov/case",
    "content": "A regulator opened an investigation into alleged misleading environmental claims and carbon-neutral wording.",
}
assert not app.is_green_negative_source(positive)
assert app.is_green_negative_source(negative)

confidence = app.build_confidence(
    ["https://example.com", "https://example.com/about"],
    {"enabled": True, "results": []},
    [{"type": "Generic environmental claim"}],
    [{"ok": True}, {"ok": True}, {"ok": False, "error": "403"}],
)
assert "A low risk score from this scan may reflect limited access" in confidence.get("reliability_warning", "")

sample = {
    "company":{"company":"Example Group"},
    "source_label":"https://example.com",
    "original_url":"https://example.com",
    "analysis_date":"2026-07-16T12:00:00+00:00",
    "global_score":55,"global_risk":"Medium",
    "green_score":62,"green_risk":"Medium",
    "social_score":43,"social_risk":"Low",
    "entity_context_indicator":{"level":"Low","note":"No negative external signal retained."},
    "claim_inventory":[{
        "claim_type":"Generic environmental claim","risk_level":"High","claim_score":74,
        "matched_phrase":"sustainable product","claim_text":"Our sustainable product supports a better future.",
        "why_flagged":"Generic environmental wording requires precise scope and evidence.",
        "evidence_needed":["scope","methodology","verification"],
        "suggested_rewrite":"Specify the exact environmental attribute, scope, method and limitations.",
        "source_label":"https://example.com/sustainability"
    }],
    "company_action_plan":[{"title":"Review claim","action":"Confirm scope and evidence."}],
    "report":{"pages_reviewed":["https://example.com","https://example.com/sustainability"]},
    "scan_inventory":{"website_pages":[],"documents":[],"failed_fetches":[],"summary":{}},
    "crawl_diagnostics":{"pages_attempted":6,"pages_failed":2,"pages_thin":0,"pages_retrieved_via_fallback":0,"detail":[]},
    "confidence":{"level":"Medium","reasons":["two sources reviewed"]},
    "external_research":{"green":{"targeted_negative_sources":[]},"social":{"targeted_negative_sources":[]}},
}

pdf = report.build_company_report_pdf(sample)
reader = PdfReader(io.BytesIO(pdf))
# v93.41: the report now separates into dedicated pages by reason for reading (overview /
# detailed evidence / external context / appendix) instead of packing as much as fits before
# each page break, so even a small scan like this one no longer fits in 2 pages.
assert len(reader.pages) >= 3, len(reader.pages)
text = "\n".join(page.extract_text() or "" for page in reader.pages)
assert "DATA RELIABILITY" in text
assert "A low risk score from this scan may reflect limited access" in text
print("V62 report regression tests passed under V65")
