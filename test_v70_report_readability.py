"""Regression coverage for the v70 reader-facing report and source precision."""
import re
from pathlib import Path

import app


def test_v70_release_and_internal_markers_removed():
    assert app.APP_VERSION == "hostable_v70_report_readability_external_source_precision"
    assert app.APP_RELEASE_LABEL == "v70"
    frontend = Path("frontend.html").read_text(encoding="utf-8")
    assert "Build {{APP_RELEASE_LABEL}}" not in frontend
    assert 'id="version"' not in frontend
    assert "downloadSourceRegisterCsv" not in frontend
    assert "The register distinguishes retrieval from actual analysis" not in frontend
    assert "Search diagnostics:" not in frontend


def test_reader_facing_typography_and_action_emphasis():
    frontend = Path("frontend.html").read_text(encoding="utf-8")
    assert "font-size:10.5px" not in frontend
    assert "font-size:11px" not in frontend
    assert "font-size:11.5px" not in frontend
    assert 'class="priority-tag"' in frontend
    assert "action-key" in frontend
    assert "Core green-claim red flags" in frontend


def test_puratos_company_pages_are_not_external_negative_sources():
    reviewed = ["https://www.puratos.com"]
    company_policy = {
        "title": "Modern Slavery and Human Trafficking Policy",
        "url": "https://www.puratos.co.uk/en/about-puratos/modern-slavery-policy",
        "content": "Puratos is committed to preventing modern slavery and forced labour.",
    }
    brand_microsite = {
        "title": "Responsible Sourcing - Puratos Vietnam",
        "url": "https://www.puratosgrandplace.com/en/sustainability/responsible-sourcing",
        "content": "Our responsible sourcing policy describes supplier due diligence.",
    }
    for source in (company_policy, brand_microsite):
        assert app.is_company_owned_source(source, "Puratos", reviewed)
        assert not app.is_negative_external_source(source)
    assert app.targeted_negative_sources(
        [company_policy, brand_microsite], "Puratos", reviewed_pages=reviewed
    ) == []


def test_genuine_independent_adverse_source_is_retained():
    reviewed = ["https://www.puratos.com"]
    adverse = {
        "title": "Authority investigates Puratos over forced-labour allegations",
        "url": "https://labour-authority.example.gov/cases/puratos-investigation",
        "content": "The authority opened an investigation after allegations of forced labour in the supply chain.",
    }
    assert not app.is_company_owned_source(adverse, "Puratos", reviewed)
    assert app.is_negative_external_source(adverse)
    retained = app.targeted_negative_sources([adverse], "Puratos", reviewed_pages=reviewed)
    assert len(retained) == 1
    assert retained[0]["polarity"] == "negative"


def test_explicit_adverse_headline_is_not_rejected_for_lacking_legal_vocabulary():
    # An unambiguous, event-framed headline must be enough on its own -- it should not
    # need a *second*, separate legal/enforcement word to be treated as negative. This
    # mirrors how a green headline like "Greenwashing in X's marketing" is already
    # accepted on the explicit term alone.
    genuine_reports = [
        {
            "title": "Modern slavery uncovered in Acme Textiles' supply chain",
            "content": "Workers described being trapped in debt bondage, with wages withheld for months.",
            "url": "https://www.independentnewsoutlet.example/modern-slavery-acme",
        },
        {
            "title": "Child labour found at Acme Textiles supplier factory",
            "content": "Interviews with former employees describe children working night shifts.",
            "url": "https://www.independentnewsoutlet.example/child-labour-acme",
        },
    ]
    for source in genuine_reports:
        assert app.is_negative_external_source(source), source["title"]

    # But a self-descriptive compliance-document title using the same vocabulary must
    # still be rejected, even when evaluated outside the domain-ownership filter -- this
    # is the exact false positive V70 was built to remove.
    policy_document = {
        "title": "Modern Slavery and Human Trafficking Policy",
        "url": "https://www.puratos.co.uk/en/about-puratos/modern-slavery-policy",
        "content": "Puratos is committed to preventing modern slavery and forced labour.",
    }
    assert not app.is_negative_external_source(policy_document)


def _blacklisted(claim_type):
    # Mirrors enrich_green_finding()'s derivation exactly, so the test can't drift from
    # the real behaviour.
    sig = app.green_blacklisted_indicator(claim_type, "", "").lower()
    return ("blacklisted-practice indicator" in sig) and not sig.startswith("no direct")


def test_empco_prohibited_vs_misleading_legal_classification():
    # Per se prohibited: Annex I UCPD blacklist practices, no case-by-case test.
    prohibited_types = [
        "Generic environmental claim",           # Annex I point 4a
        "Climate-neutrality or offsetting claim", # Annex I point 4c -- the product-level offset example
        "Sustainability label / certification claim", # Annex I point 2a
        "Legal requirement presented as green benefit",
    ]
    for claim_type in prohibited_types:
        result = app.green_legal_classification(claim_type, _blacklisted(claim_type))
        assert result["label"] == "Prohibited", claim_type
        assert "Annex I" in result["basis"] or "UCPD" in result["basis"]

    # Misleading, case-by-case: assessed individually under the amended UCPD Art. 6/7 --
    # including "fully recyclable" / absolute wording, which is the exact counter-example.
    case_by_case_types = [
        "Absolute or purity environmental wording",  # covers "fully recyclable"
        "Comparative environmental claim",
        "Future environmental-performance claim",
        "Visual green-claim indicator",
    ]
    for claim_type in case_by_case_types:
        result = app.green_legal_classification(claim_type, _blacklisted(claim_type))
        assert result["label"] == "Misleading (case-by-case)", claim_type
        assert "individually" in result["basis"].lower()


def test_legal_classification_flows_into_claim_inventory_and_pdf():
    result = app.analyse_uploaded_document(
        "policy.txt",
        "This product is 100% carbon neutral thanks to our offset program. "
        "It is also fully recyclable and eco-friendly.",
        "Acme Corp",
    )
    green_claims = {c["claim_type"]: c for c in result["claim_inventory"] if c["dimension"] == "Green"}
    assert green_claims["Climate-neutrality or offsetting claim"]["legal_classification"]["label"] == "Prohibited"
    assert green_claims["Absolute or purity environmental wording"]["legal_classification"]["label"] == "Misleading (case-by-case)"

    import report_pdf
    pdf_bytes = report_pdf.build_company_report_pdf(result)
    assert pdf_bytes[:4] == b"%PDF"

    # No PDF text block may extend past the page width -- the exact failure mode a past
    # release had to fix for the risk badge (see the layout comment in claim_card()).
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    saw_classification_text = False
    for page in doc:
        if "EMPCO CLASSIFICATION" in page.get_text().upper():
            saw_classification_text = True
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            assert block["bbox"][2] <= page.rect.width + 0.5, f"text overflow: {block['bbox']}"
    assert saw_classification_text


def test_actions_keep_green_and_social_claim_areas_separate():
    green = [{"risk": "High", "type": "Generic environmental claim", "problematic_terms": ["sustainable"]}]
    social = [{"risk": "High", "type": "Human-rights or labour-rights claim", "problematic_terms": ["responsible"]}]
    actions = app.build_green_social_actions(green, social, {"audience": "Client-facing communication"}, "Puratos")
    assert "Generic environmental claim" in actions[0]["action"]
    assert "Human-rights or labour-rights claim" not in actions[0]["action"]
    assert len(actions[0]["action"]) < 430


def test_prohibited_label_has_no_per_se_suffix_anywhere():
    # The badge/label itself must read just "Prohibited"; the per-se / no-case-by-case
    # nuance still lives in the longer basis text, not in the short label shown at a glance.
    result = app.green_legal_classification("Climate-neutrality or offsetting claim", True)
    assert result["label"] == "Prohibited"
    assert "per se" not in result["label"].lower()

    frontend = Path("frontend.html").read_text(encoding="utf-8")
    assert "Prohibited (per se)" not in frontend
    assert "'Prohibited (per se)'" not in frontend

    scan = app.analyse_uploaded_document(
        "policy.txt", "This product is 100% carbon neutral thanks to our offset program.", "Acme Corp",
    )
    import report_pdf
    pdf_bytes = report_pdf.build_company_report_pdf(scan)
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = "".join(page.get_text() for page in doc)
    assert "Prohibited (per se)" not in full_text
    assert "Prohibited" in full_text


def test_classification_is_always_visible_without_expanding_the_card():
    # The explanation must sit inside <summary> (rendered before any click/expand), not
    # only in a hover title="" tooltip or inside the collapsed <details> body.
    script = re.search(r"<script[^>]*>(.*?)</script>", Path("frontend.html").read_text(encoding="utf-8"), re.S).group(1)
    fn_start = script.index("function clusterCard(")
    depth = 0; i = script.index("{", fn_start); start = fn_start; j = i
    while True:
        if script[j] == "{":
            depth += 1
        elif script[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    fn_src = script[start:j + 1]
    summary_end = fn_src.index("</summary>")
    summary_part = fn_src[:summary_end]
    assert "lcLine" in summary_part, "classification line must be built inside the always-visible <summary> part"
    assert 'title="${esc(lc.basis' not in fn_src, "must not rely on a hover-only tooltip for the explanation"


def test_dashboard_red_flags_deduplicated_and_core_tagged():
    green = [{
        "type": "Climate-neutrality or offsetting claim", "risk": "High",
        "problematic_terms": ["carbon neutral"], "source_label": "policy.txt",
        "legal_classification": {"label": "Prohibited", "basis": "Annex I point 4c UCPD..."},
    }]
    social = [{
        "type": "Forced-labour product or supply-chain claim", "risk": "High",
        "source_label": "policy.txt",
    }]
    result = app.build_dashboard_red_flags(green, social, {}, {}, {"level": "High"}, {"level": "Very high"}, {})

    # Exactly one Forced Labour Regulation flag -- not the old two differently-worded ones.
    reg_texts = [f["text"] for f in result["regulatory"]]
    forced_labour_flags = [t for t in reg_texts if "Forced Labour Regulation" in t]
    assert len(forced_labour_flags) == 1, forced_labour_flags

    # The Prohibited claim and the forced-labour claim are tagged core; sector/context
    # sensitivity flags (previously silently dropped) are present but not core.
    assert result["green"][0]["core"] is True
    assert result["social"][0]["core"] is True
    empco_flag = next(t for t in reg_texts if "EmpCo readiness" in t)
    assert "Annex I blacklist pattern" in empco_flag
    non_core_context = [f for f in result["regulatory"] if not f["core"]]
    assert any("sector" in f["text"].lower() for f in non_core_context)
    assert any("context sensitivity" in f["text"].lower() for f in non_core_context)
