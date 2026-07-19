"""Regression coverage for the v70 reader-facing report and source precision."""
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


def test_actions_keep_green_and_social_claim_areas_separate():
    green = [{"risk": "High", "type": "Generic environmental claim", "problematic_terms": ["sustainable"]}]
    social = [{"risk": "High", "type": "Human-rights or labour-rights claim", "problematic_terms": ["responsible"]}]
    actions = app.build_green_social_actions(green, social, {"audience": "Client-facing communication"}, "Puratos")
    assert "Generic environmental claim" in actions[0]["action"]
    assert "Human-rights or labour-rights claim" not in actions[0]["action"]
    assert len(actions[0]["action"]) < 430
