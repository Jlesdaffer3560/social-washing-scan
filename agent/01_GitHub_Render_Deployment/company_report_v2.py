"""
Durably Sustainability Scan - two-page company report v2
=========================================================

Drop-in Flask module. No new runtime dependency is required beyond Flask/Jinja,
which the existing application already uses.

Typical integration
-------------------
from company_report_v2 import register_company_report_v2
register_company_report_v2(app, report_provider=lambda: session.get("last_scan_result"))

The route will be available at:
    /company-report-v2
    /company-report-v2?print=1

It also accepts a JSON payload:
    POST /company-report-v2
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from html import escape
import json
import re
import textwrap
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from markupsafe import Markup
except ImportError:  # pragma: no cover
    Markup = str  # type: ignore


REPORT_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ company }} - Durably company claim-risk report</title>
<style>
:root{
  --navy:#173e52; --teal:#2c766b; --teal-dark:#195a53;
  --green:#2f7d55; --green-soft:#eaf5ef; --blue-soft:#eff5f8;
  --amber:#a87311; --amber-soft:#fff6df; --red:#af3d43;
  --grey-900:#263238; --grey-700:#52616a; --grey-500:#7a8a93;
  --grey-300:#d8e1e5; --grey-150:#edf1f3; --grey-100:#f7f9fa;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:#e9eef1;
  font-family:Arial,Helvetica,sans-serif;
  color:var(--grey-700);
  -webkit-print-color-adjust:exact;
  print-color-adjust:exact;
}
.report-controls{
  position:fixed;right:18px;top:18px;z-index:30;
  display:flex;gap:8px;
}
.report-controls button{
  border:0;border-radius:5px;padding:9px 13px;cursor:pointer;
  font-size:13px;font-weight:700;
}
.report-controls .primary{background:var(--navy);color:#fff}
.report-controls .secondary{background:#fff;color:var(--navy);border:1px solid var(--grey-300)}
.page{
  width:210mm;height:297mm;margin:12px auto;background:#fff;
  padding:11mm 13mm 14mm;position:relative;overflow:hidden;
  page-break-after:always;
}
.page:last-child{page-break-after:auto}
.header{
  display:grid;grid-template-columns:minmax(0,2fr) minmax(45mm,1fr);
  gap:8mm;border-bottom:1.5px solid var(--navy);
  padding-bottom:3mm;margin-bottom:3mm;
}
.brand{font-size:8.2pt;font-weight:700;color:var(--teal-dark);letter-spacing:.3px}
h1{font-size:20pt;line-height:1.04;margin:1.5mm 0 .8mm;color:var(--navy)}
.subtitle{font-size:8.6pt;color:var(--grey-700)}
.meta{text-align:right;font-size:7pt;line-height:1.32;color:var(--grey-700);overflow-wrap:anywhere}
.meta strong{font-size:6.3pt;color:var(--grey-500);letter-spacing:.2px}
.section{
  font-size:9.2pt;font-weight:700;color:var(--navy);
  letter-spacing:.2px;margin:3.4mm 0 1.7mm;
}
.summary{
  display:grid;grid-template-columns:minmax(0,3fr) minmax(38mm,1.15fr);
  border:1px solid var(--grey-300);margin-bottom:3.5mm;
}
.summary>div{padding:2.8mm 3.2mm;font-size:7.2pt;line-height:1.32}
.summary-main{background:var(--amber-soft);border-left:3px solid var(--amber)}
.summary-note{background:var(--grey-100);border-left:1px solid var(--grey-300);font-size:6.5pt!important}
.scores{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2.5mm}
.score{
  border:1px solid var(--grey-300);padding:2.6mm;
  border-left:3px solid var(--amber);min-height:25mm;overflow:hidden;
}
.score.low{border-left-color:var(--green)}
.score.high,.score.very-high{border-left-color:var(--red)}
.eyebrow{font-size:6.2pt;font-weight:700;color:var(--teal-dark);text-transform:uppercase}
.number{font-size:18pt;line-height:1;font-weight:700;color:var(--navy);margin:2.3mm 0 .8mm}
.number small{font-size:6.6pt}
.risk{font-size:7.8pt;font-weight:700;color:var(--amber)}
.risk.low{color:var(--green)}.risk.high,.risk.very-high{color:var(--red)}
.small{font-size:6.35pt;line-height:1.25}.body{font-size:7.1pt;line-height:1.3}
table{width:100%;border-collapse:collapse;font-size:6.7pt;line-height:1.25;table-layout:fixed}
th{background:var(--navy);color:#fff;text-align:left;padding:1.9mm;font-size:6.3pt}
td{padding:1.9mm;border:1px solid var(--grey-300);vertical-align:top;overflow-wrap:anywhere}
tr:nth-child(even) td{background:var(--grey-100)}
.col-rank{width:8mm}.col-area{width:58mm}.col-wording{width:48mm}
mark{background:#fff1a8;padding:0 1px}
.claim{border:1px solid var(--grey-300);margin-bottom:2.6mm;break-inside:avoid}
.claim-head{
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4mm;
  padding:2.2mm 2.8mm;background:var(--blue-soft);
  border-left:3px solid var(--teal);font-size:8.3pt;font-weight:700;color:var(--navy)
}
.claim-risk{color:var(--red)}
.claim-body{padding:2.2mm 2.8mm;font-size:6.85pt;line-height:1.29}
.source{font-size:6.1pt;color:var(--grey-500);margin-bottom:1.7mm;overflow-wrap:anywhere}
.excerpt{background:#fffdf6;padding:1.6mm;margin:1.4mm 0 1.8mm}
.claim-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:3.5mm;margin:2mm 0}
.claim-grid>div:first-child{border-right:1px solid var(--grey-300);padding-right:3.5mm}
.label{font-size:6.2pt;font-weight:700;color:var(--teal-dark);text-transform:uppercase;margin-bottom:.7mm}
.actions{border:1px solid var(--grey-300)}
.action{
  display:grid;grid-template-columns:10mm minmax(0,1fr);
  border-bottom:1px solid var(--grey-300);background:var(--grey-100)
}
.action:last-child{border-bottom:0}
.action>div{padding:2.2mm 2.8mm;font-size:6.65pt;line-height:1.27}
.action-num{
  font-size:8.6pt!important;font-weight:700;color:var(--navy);
  text-align:center;border-right:1px solid var(--grey-300)
}
.bottom{
  display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.08fr);
  border:1px solid var(--grey-300);margin-top:2.7mm
}
.bottom>div{padding:2.6mm}
.bottom>div+div{border-left:1px solid var(--grey-300)}
.bottom h3{font-size:7.5pt;margin:0 0 1.5mm;color:var(--navy)}
.bottom ul{margin:0;padding-left:4mm}
.bottom li{font-size:6.2pt;line-height:1.25;margin-bottom:.8mm;overflow-wrap:anywhere}
.muted{color:var(--grey-500);font-style:italic}
.footer{
  position:absolute;left:13mm;right:13mm;bottom:6.5mm;
  border-top:1px solid var(--grey-300);padding-top:1.8mm;
  display:flex;justify-content:space-between;gap:8mm;
  font-size:5.4pt;font-style:italic;color:var(--grey-500)
}
.footer span:first-child{max-width:145mm}
@page{size:A4;margin:0}
@media print{
  body{background:#fff}
  .page{margin:0;box-shadow:none}
  .report-controls{display:none!important}
}
</style>
</head>
<body>
<div class="report-controls">
  <button class="primary" onclick="window.print()">Print / Save as PDF</button>
  <button class="secondary" onclick="window.close()">Close</button>
</div>

<section class="page">
  <header class="header">
    <div>
      <div class="brand">DURABLY SUSTAINABILITY SCAN</div>
      <h1>{{ company }}</h1>
      <div class="subtitle">Company claim-risk report · Assessment overview</div>
    </div>
    <div class="meta">
      <strong>REVIEWED SOURCE</strong><br>
      {{ source_display }}<br>
      {{ analysis_date }} · {{ scan_type }}<br>
      {{ coverage_short }}<br>
      Confidence: {{ confidence_level }}
    </div>
  </header>

  <div class="summary">
    <div class="summary-main">
      <b>Overall result: {{ global_score }}/100 — {{ global_risk }} claim risk.</b>
      {{ executive_summary }}
    </div>
    <div class="summary-note">{{ entity_resolution_note }}</div>
  </div>

  <div class="section">SCORE OVERVIEW</div>
  <div class="scores">
    <div class="score {{ global_risk_class }}">
      <div class="eyebrow">Overall claims risk</div>
      <div class="number">{{ global_score }}<small>/100</small></div>
      <div class="risk {{ global_risk_class }}">{{ global_risk }}</div>
    </div>
    <div class="score {{ green_risk_class }}">
      <div class="eyebrow">Green claims risk</div>
      <div class="number">{{ green_score }}<small>/100</small></div>
      <div class="risk {{ green_risk_class }}">{{ green_risk }}</div>
    </div>
    <div class="score {{ social_risk_class }}">
      <div class="eyebrow">Social claims risk</div>
      <div class="number">{{ social_score }}<small>/100</small></div>
      <div class="risk {{ social_risk_class }}">{{ social_risk }}</div>
    </div>
    <div class="score {{ entity_context_class }}">
      <div class="eyebrow">Entity context</div>
      <div class="number" style="font-size:14pt">{{ entity_context }}</div>
      <div class="risk {{ entity_context_class }}">{{ entity_context }}</div>
      <div class="small">{{ entity_context_short }}</div>
    </div>
  </div>

  <div class="section">TOP RISK DRIVERS</div>
  <table>
    <thead><tr><th class="col-rank">#</th><th class="col-area">Claim area</th><th class="col-wording">Flagged wording</th><th>Source</th></tr></thead>
    <tbody>
    {% for finding in top_findings %}
      <tr>
        <td>{{ loop.index }}</td>
        <td><b>{{ finding.title }}</b><br><span class="muted">{{ finding.risk }}</span></td>
        <td>{{ finding.flagged_wording }}</td>
        <td>{{ finding.source_short }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="section">MOST MATERIAL FINDING</div>
  {% if material_finding %}
  <article class="claim">
    <div class="claim-head">
      <span>{{ material_finding.title }}</span>
      <span class="claim-risk">{{ material_finding.risk }}</span>
    </div>
    <div class="claim-body">
      <div class="source">Source: {{ material_finding.source }}</div>
      <div class="excerpt">{{ material_finding.excerpt | highlight(material_finding.flagged_wording) }}</div>
      <div class="claim-grid">
        <div><div class="label">Why it matters</div>{{ material_finding.why_it_matters }}</div>
        <div><div class="label">Evidence gap</div>{{ material_finding.evidence_gap }}</div>
      </div>
      <div><span class="label">Recommended wording</span> {{ material_finding.recommended_wording }}</div>
    </div>
  </article>
  {% endif %}

  <footer class="footer">
    <span>Indicative screening only — not legal advice. Results require legal, compliance and subject-matter review before external use.</span>
    <span>© Durably · {{ company }} · Page 1 of 2</span>
  </footer>
</section>

<section class="page">
  <header class="header">
    <div>
      <div class="brand">DURABLY SUSTAINABILITY SCAN</div>
      <h1>{{ company }}</h1>
      <div class="subtitle">Company claim-risk report · Priority findings and actions</div>
    </div>
    <div class="meta">
      <strong>REVIEWED SOURCE</strong><br>
      {{ source_display }}<br>
      {{ analysis_date }} · {{ scan_type }}<br>
      {{ coverage_short }}<br>
      Confidence: {{ confidence_level }}
    </div>
  </header>

  <div class="section">ADDITIONAL PRIORITY CLAIMS</div>
  {% for finding in additional_findings %}
  <article class="claim">
    <div class="claim-head">
      <span>{{ finding.title }}</span>
      <span class="claim-risk">{{ finding.risk }}</span>
    </div>
    <div class="claim-body">
      <div class="source">Source: {{ finding.source }}</div>
      <div class="excerpt">{{ finding.excerpt | highlight(finding.flagged_wording) }}</div>
      <div class="claim-grid">
        <div><div class="label">Why it matters</div>{{ finding.why_it_matters }}</div>
        <div><div class="label">Evidence gap</div>{{ finding.evidence_gap }}</div>
      </div>
      <div><span class="label">Recommended wording</span> {{ finding.recommended_wording }}</div>
    </div>
  </article>
  {% endfor %}

  <div class="section">PRIORITY ACTIONS</div>
  <div class="actions">
  {% for action in priority_actions %}
    <div class="action">
      <div class="action-num">{{ loop.index }}</div>
      <div><b>{{ action.title }}</b><br>{{ action.description }}</div>
    </div>
  {% endfor %}
  </div>

  <div class="bottom">
    <div>
      <h3>External signals and coverage</h3>
      {% if external_signals %}
      <ul>{% for signal in external_signals %}<li>{{ signal }}</li>{% endfor %}</ul>
      {% else %}
      <div class="body muted">No relevant external public-source signal was retained in this scan.</div>
      {% endif %}
      <h3 style="margin-top:2.5mm">Sources reviewed</h3>
      <ul>{% for source in sources_reviewed %}<li>{{ source }}</li>{% endfor %}</ul>
    </div>
    <div>
      <h3>Confidence and methodology</h3>
      <div class="body"><b>Confidence:</b> {{ confidence_level }}. {{ confidence_reason }}</div>
      <div class="body" style="margin-top:2mm">
        <b>Risk bands:</b> 0–44 Low · 45–74 Medium · 75–89 High · 90–100 Very high.
        EmpCo / Directive (EU) 2024/825 is applied to consumer-facing environmental and selected social claims.
        The EU Forced Labour Regulation lens is applied to forced-labour and supply-chain wording.
      </div>
      <div class="body" style="margin-top:2mm"><b>Full methodology:</b> {{ methodology_reference }}</div>
    </div>
  </div>

  <footer class="footer">
    <span>Indicative screening only — not legal advice. Results require legal, compliance and subject-matter review before external use.</span>
    <span>© Durably · {{ company }} · Page 2 of 2</span>
  </footer>
</section>

<script>
(function(){
  const params = new URLSearchParams(window.location.search);
  if(params.get("print")==="1"){
    window.addEventListener("load", function(){
      setTimeout(function(){ window.print(); }, 250);
    });
  }
})();
</script>
</body>
</html>"""


def _nested(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _first(data: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        value = _nested(data, path, None)
        if value is not None and value != "":
            return value
    return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _risk_from_score(score: int) -> str:
    if score <= 44:
        return "Low"
    if score <= 74:
        return "Medium"
    if score <= 89:
        return "High"
    return "Very high"


def _risk_class(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    if "very" in text and "high" in text:
        return "very-high"
    if "high" in text:
        return "high"
    if "low" in text:
        return "low"
    return "medium"


def _shorten(value: Any, width: int, placeholder: str = "…") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return textwrap.shorten(text, width=width, placeholder=placeholder)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _source_short(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://", "", text)
    return _shorten(text, 48)


def _normalise_finding(item: Any) -> dict[str, str]:
    if not isinstance(item, Mapping):
        return {
            "title": "Sustainability claim",
            "risk": "Review",
            "source": "",
            "source_short": "",
            "excerpt": _shorten(item, 300),
            "flagged_wording": "",
            "why_it_matters": "The detected wording requires claim-specific review.",
            "evidence_gap": "Claim-specific evidence and scope should be confirmed.",
            "recommended_wording": "Use precise wording and disclose scope, method, evidence, period and limitations.",
        }

    title = _first(
        item, "title", "claim_area", "category", "claim_type", "name",
        default="Sustainability claim"
    )
    source = _first(item, "source", "url", "document", "source_url", default="")
    excerpt = _first(item, "excerpt", "exact_wording", "claim", "text", "passage", default="")
    flagged = _first(item, "flagged_wording", "trigger", "trigger_term", "matched_wording", default="")
    risk = _first(item, "risk", "severity", "risk_level", default="Review")

    return {
        "title": _shorten(title, 90),
        "risk": _shorten(risk, 20),
        "source": _shorten(source, 150),
        "source_short": _source_short(source),
        "excerpt": _shorten(excerpt, 430),
        "flagged_wording": _shorten(flagged, 80),
        "why_it_matters": _shorten(
            _first(item, "why_it_matters", "reason", "explanation", "risk_explanation",
                   default="The wording may be broader or more absolute than the available evidence supports."),
            300,
        ),
        "evidence_gap": _shorten(
            _first(item, "evidence_gap", "missing_evidence", "gaps",
                   default="Scope, methodology, evidence, reporting period and limitations should be confirmed."),
            230,
        ),
        "recommended_wording": _shorten(
            _first(item, "recommended_wording", "recommendation", "recommended_action",
                   default="Use precise, claim-specific wording and disclose scope, methodology, evidence, period and limitations."),
            330,
        ),
    }


def _normalise_action(item: Any, index: int) -> dict[str, str]:
    if isinstance(item, Mapping):
        title = _first(item, "title", "action", "name", default=f"Priority action {index}")
        description = _first(item, "description", "detail", "recommendation", "text", default="")
    else:
        title = f"Priority action {index}"
        description = item
    return {
        "title": _shorten(title, 95),
        "description": _shorten(description, 310),
    }


def normalise_report_data(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a flexible scan-result dictionary into the fixed report schema."""
    data = deepcopy(dict(raw or {}))

    global_score = _as_int(_first(
        data, "global_score", "overall_score", "scores.global",
        "score_summary.global", "claim_risk_score", default=0
    ))
    green_score = _as_int(_first(
        data, "green_score", "scores.green", "score_summary.green", default=0
    ))
    social_score = _as_int(_first(
        data, "social_score", "scores.social", "score_summary.social", default=0
    ))

    global_risk = str(_first(
        data, "global_risk", "overall_risk", "risk_band",
        default=_risk_from_score(global_score)
    ))
    green_risk = str(_first(
        data, "green_risk", "scores.green_risk",
        default=_risk_from_score(green_score)
    ))
    social_risk = str(_first(
        data, "social_risk", "scores.social_risk",
        default=_risk_from_score(social_score)
    ))

    findings_raw = _first(
        data, "top_findings", "priority_findings", "findings",
        "risk_drivers", "claims", default=[]
    )
    findings = [_normalise_finding(x) for x in _list(findings_raw)][:3]

    # Ensure the fixed two-page template always has up to three findings.
    if not findings:
        findings = [_normalise_finding({
            "title": "No material claim signal retained",
            "risk": "Low",
            "excerpt": "No material sustainability claim signal was retained in the reviewed material.",
            "why_it_matters": "No material wording issue was retained in this first-pass screening.",
            "evidence_gap": "Not applicable.",
            "recommended_wording": "Continue maintaining claim-specific evidence and approval records.",
        })]

    actions_raw = _first(
        data, "priority_actions", "recommended_actions", "actions",
        "recommendations", default=[]
    )
    actions = [_normalise_action(x, i + 1) for i, x in enumerate(_list(actions_raw)[:3])]
    while len(actions) < 3:
        defaults = [
            ("Review priority claims", "Review the exact wording, audience, scope and supporting evidence for each retained priority claim."),
            ("Close evidence gaps", "Create or update claim-specific evidence files with methodology, period, ownership, limitations and approval status."),
            ("Implement claim governance", "Introduce legal, compliance, sustainability and marketing approval before material sustainability claims are published."),
        ]
        title, description = defaults[len(actions)]
        actions.append({"title": title, "description": description})

    external_signals = [
        _shorten(
            x.get("summary") if isinstance(x, Mapping) else x,
            230,
        )
        for x in _list(_first(data, "external_signals", "retained_external_signals", default=[]))[:2]
    ]
    external_signals = [x for x in external_signals if x]

    sources = [
        _shorten(
            x.get("url") if isinstance(x, Mapping) else x,
            145,
        )
        for x in _list(_first(
            data, "sources_reviewed", "coverage.sources", "reviewed_sources", default=[]
        ))[:4]
    ]
    sources = [x for x in sources if x]

    company = _first(data, "company", "company_name", "entity_name", default="Company")
    source_display = _first(
        data, "source_display", "reviewed_source", "source_url", "url",
        default=(sources[0] if sources else "")
    )

    context = {
        "company": _shorten(company, 70),
        "source_display": _shorten(source_display, 120),
        "analysis_date": _shorten(
            _first(data, "analysis_date", "date", "scan_date", default=date.today().isoformat()),
            20,
        ),
        "scan_type": _shorten(_first(data, "scan_type", "assessment_type", default="Website scan"), 35),
        "coverage_short": _shorten(
            _first(data, "coverage_short", "coverage.summary", default="Scope reported by the scan"),
            80,
        ),
        "confidence_level": _shorten(
            _first(data, "confidence_level", "confidence.level", "confidence", default="Medium"),
            20,
        ),
        "confidence_reason": _shorten(
            _first(
                data, "confidence_reason", "confidence.reason",
                default="The confidence level reflects source access, claim coverage and external-search coverage."
            ),
            280,
        ),
        "global_score": global_score,
        "green_score": green_score,
        "social_score": social_score,
        "global_risk": global_risk,
        "green_risk": green_risk,
        "social_risk": social_risk,
        "global_risk_class": _risk_class(global_risk),
        "green_risk_class": _risk_class(green_risk),
        "social_risk_class": _risk_class(social_risk),
        "entity_context": _shorten(
            _first(data, "entity_context", "entity_context.level", default="Not assessed"),
            25,
        ),
        "entity_context_class": _risk_class(
            _first(data, "entity_context", "entity_context.level", default="Medium")
        ),
        "entity_context_short": _shorten(
            _first(
                data, "entity_context_short", "entity_context.summary",
                default="Entity context is shown separately from the claim-risk scores."
            ),
            120,
        ),
        "executive_summary": _shorten(
            _first(
                data, "executive_summary", "summary", "overall_summary",
                default="The result reflects the retained claim signals, evidence gaps and relevant regulatory lenses."
            ),
            420,
        ),
        "entity_resolution_note": _shorten(
            _first(
                data, "entity_resolution_note", "resolution_note",
                default="Verify the reviewed entity and source scope before relying on this result."
            ),
            230,
        ),
        "top_findings": findings,
        "material_finding": findings[0] if findings else None,
        "additional_findings": findings[1:3],
        "priority_actions": actions,
        "external_signals": external_signals,
        "sources_reviewed": sources or [_shorten(source_display, 145)],
        "methodology_reference": _shorten(
            _first(
                data, "methodology_reference", "methodology_url",
                default="See the detailed Durably Sustainability Scan methodology PDF."
            ),
            170,
        ),
    }
    return context


def _highlight_filter(text: Any, needle: Any) -> Markup:
    """Safely highlight the exact detected wording in the claim excerpt."""
    safe_text = escape(str(text or ""))
    safe_needle = escape(str(needle or "")).strip()
    if not safe_needle:
        return Markup(safe_text)

    pattern = re.compile(re.escape(safe_needle), re.IGNORECASE)
    highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", safe_text)
    return Markup(highlighted)


def render_company_report_html(report_data: Mapping[str, Any]) -> str:
    """Render the fixed two-page report to an HTML string."""
    from jinja2 import Environment, BaseLoader, select_autoescape

    env = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    env.filters["highlight"] = _highlight_filter
    template = env.from_string(REPORT_TEMPLATE)
    return template.render(**normalise_report_data(report_data))


def register_company_report_v2(
    app: Any,
    report_provider: Callable[[], Mapping[str, Any] | None] | None = None,
    route: str = "/company-report-v2",
) -> None:
    """
    Register the report route on an existing Flask application.

    GET:
      Uses report_provider() when supplied.
    POST:
      Accepts the report dictionary as JSON.
    """
    from flask import Response, jsonify, request

    endpoint = "durably_company_report_v2"

    @app.route(route, methods=["GET", "POST"], endpoint=endpoint)
    def company_report_v2_route() -> Any:
        if request.method == "POST":
            payload = request.get_json(silent=True)
            if not isinstance(payload, Mapping):
                return jsonify({
                    "error": "Send a JSON object containing the company-report data."
                }), 400
        else:
            payload = report_provider() if report_provider else None

        if not isinstance(payload, Mapping):
            return jsonify({
                "error": (
                    "No report data available. Supply report_provider when registering "
                    "the route or POST a JSON object to this endpoint."
                )
            }), 404

        html = render_company_report_html(payload)
        return Response(html, mimetype="text/html")


# Optional local smoke test:
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", help="Path to report-data JSON")
    parser.add_argument("--output", default="company_report_v2.html")
    args = parser.parse_args()

    raw = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    Path(args.output).write_text(render_company_report_html(raw), encoding="utf-8")
    print(f"Created {args.output}")
