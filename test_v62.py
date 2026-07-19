"""Offline regression tests for v62. Run: python test_v62.py"""
import importlib.util
import io
import json
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

assert app.APP_VERSION == "hostable_v70_report_readability_external_source_precision"

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
assert len(reader.pages) == 2
text = "\n".join(page.extract_text() or "" for page in reader.pages)
assert "DATA RELIABILITY" in text
assert "A low risk score from this scan may reflect limited access" in text
print("V62 report regression tests passed under V65")
