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

assert app.APP_VERSION == "hostable_v65_generic_entity_lock_pdf_layout_fix"

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

sample = json.loads((ROOT / "PREVIEW_V62" / "frontend_preview_payload.json").read_text())
sample["data_reliability_warning"] = (
    "2 of 6 page fetches failed. A low risk score from this scan may reflect limited access "
    "to the site's content, not necessarily a genuine absence of risky claims."
)
pdf = report.build_company_report_pdf(sample)
reader = PdfReader(io.BytesIO(pdf))
assert len(reader.pages) == 2
text = "\n".join(page.extract_text() or "" for page in reader.pages)
assert "DATA RELIABILITY" in text
assert "A low risk score from this scan may reflect limited access" in text
print("V62 report regression tests passed under V65")
