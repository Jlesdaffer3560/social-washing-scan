"""V71 regression tests for generic external-signal discovery and filtering."""
import json

import app


REVIEWED_SHEIN = ["https://www.shein.com", "https://www.sheingroup.com"]


GREEN_SOURCES = [
    {
        "title": "Italian regulator hits Shein with 1 million euro greenwashing fine",
        "url": "https://www.reuters.com/sustainability/shein-greenwashing-fine",
        "content": "The competition authority fined Shein for misleading environmental and sustainability claims.",
    },
    {
        "title": "Commission and national authorities urge SHEIN to respect EU consumer protection laws",
        "url": "https://ec.europa.eu/commission/presscorner/detail/en/ip_25_1331",
        "content": "Misleading sustainability claims provided false or deceptive information about environmental benefits.",
    },
]

SOCIAL_SOURCES = [
    {
        "title": "SHEIN, ultra-fast fashion and forced labour risks",
        "url": "https://www.business-humanrights.org/documents/40793/2024_Shein_briefing.pdf",
        "content": "The findings identify forced labour risks and risks of worker exploitation in suppliers.",
    },
    {
        "title": "Interviews with factory employees refute Shein's promises to make improvements",
        "url": "https://www.publiceye.ch/en/topics/fashion/interviews-with-factory-employees-refute-sheins-promises-to-make-improvements",
        "content": "75-hour weeks are still the norm. Workers reported 12-hour days and illegal working hours.",
    },
]


def test_clear_shein_green_sources_are_retained():
    retained = app.targeted_negative_sources(
        GREEN_SOURCES, "SHEIN", 5, REVIEWED_SHEIN, app.is_green_negative_source
    )
    assert len(retained) == 2
    assert all(item["polarity"] == "negative" for item in retained)


def test_clear_shein_social_sources_are_retained():
    retained = app.targeted_negative_sources(
        SOCIAL_SOURCES, "SHEIN", 5, REVIEWED_SHEIN, app.is_negative_external_source
    )
    assert len(retained) == 2
    assert {item["category"] for item in retained} == {"NGO / civil society"}


def test_company_statement_on_public_register_is_not_an_external_signal():
    statement = {
        "title": "SHEIN Australia Modern Slavery Act Transparency Statement",
        "url": "https://modernslaveryregister.gov.au/statements/shein.pdf",
        "content": "This modern slavery statement describes our forced-labour risk assessment, due diligence and zero-tolerance policy.",
    }
    assert not app.is_negative_external_source(statement)
    assert app.targeted_negative_sources(
        [statement], "SHEIN", 5, REVIEWED_SHEIN, app.is_negative_external_source
    ) == []


def test_positive_worker_announcement_remains_excluded():
    positive = {
        "title": "SHEIN launches worker well-being partnership",
        "url": "https://news.example/shein-worker-partnership",
        "content": "The company announced a collaboration and a new initiative for suppliers.",
    }
    assert not app.is_negative_external_source(positive)


def test_competitor_primary_article_is_rejected():
    competitor = {
        "title": "Zara accused of labour-rights violations at suppliers",
        "url": "https://news.example/zara-supplier-investigation",
        "content": "The article is about Zara. Shein is mentioned once in a comparison of fast-fashion companies.",
    }
    assert not app.entity_match_details(competitor, "SHEIN", REVIEWED_SHEIN)["matched"]


def test_query_design_is_generic_and_uses_external_source_pools():
    for dimension in ("green", "social"):
        specs = app._v71_query_specs("Example Holdings", dimension)
        assert len(specs) >= 4
        assert all('"example"' in spec["query"].lower() for spec in specs)
        assert any(spec.get("topic") == "news" for spec in specs)
        constrained = [spec for spec in specs if spec.get("include_domains")]
        assert constrained and all("example.com" not in spec["include_domains"] for spec in constrained)


def test_full_discovery_pipeline_retains_generic_company_signals():
    green = {
        "title": "Regulator fines Example over misleading environmental claims",
        "url": "https://competition-authority.gov/cases/example-green-claims",
        "content": "The authority fined Example after an environmental claims investigation.",
    }
    social = {
        "title": "NGO report alleges forced labour risks at Example suppliers",
        "url": "https://workerjustice.org/reports/example-suppliers",
        "content": "The report alleges forced labour and worker exploitation risks.",
    }
    old_search = app.search_public_sources

    def fake_search(query, max_results=8, topic="general", include_domains=None, exclude_domains=None):
        return ([green] if "environment" in query or "greenwashing" in query else [social]), [
            {"provider": "Test provider", "status": "ok", "results": 1}
        ]

    app.search_public_sources = fake_search
    try:
        green_ranked, _, _, _, _, green_diag = app._v64_search_dimension(
            "Example", [], "green", ["https://www.example.com"]
        )
        social_ranked, _, _, _, _, social_diag = app._v64_search_dimension(
            "Example", [], "social", ["https://www.example.com"]
        )
    finally:
        app.search_public_sources = old_search
    assert green_ranked and green_diag["retained_count"] >= 1
    assert social_ranked and social_diag["retained_count"] >= 1


def test_tavily_payload_receives_source_controls():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"results": []}).encode()

    old_key, old_urlopen = app.TAVILY_API_KEY, app.urlopen
    app.TAVILY_API_KEY = "test-key"

    def fake_urlopen(request, timeout=0, context=None):
        captured.update(json.loads(request.data.decode()))
        return Response()

    app.urlopen = fake_urlopen
    try:
        app.tavily_search(
            '"Example" greenwashing', 8, topic="news",
            include_domains=["reuters.com"], exclude_domains=["example.com"]
        )
    finally:
        app.TAVILY_API_KEY, app.urlopen = old_key, old_urlopen
    assert captured["topic"] == "news"
    assert captured["include_domains"] == ["reuters.com"]
    assert captured["exclude_domains"] == ["example.com"]


def test_frontend_balances_green_and_social_sources():
    frontend = open("frontend.html", encoding="utf-8").read()
    assert "balanced.push(green[i])" in frontend
    assert "balanced.push(social[i])" in frontend
    assert "all.slice(0,8)" in frontend
