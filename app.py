#!/usr/bin/env python3
"""
Social Washing Scan - Hostable v6

Render-ready Python app using only standard library.
Frontend is stored separately in frontend.html to avoid large embedded-string errors.

Start:
    python app.py
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json
import os
import ssl
import socket
import ipaddress
import datetime

PORT = int(os.environ.get("PORT", "8000"))
HOST = "0.0.0.0"
MAX_TEXT_CHARS = 60000
APP_DIR = Path(__file__).resolve().parent

SCORING_CRITERIA = [
    {"key": "specificity", "label": "Specificity of the claim", "weight": 15, "explanation": "Whether the statement is precise, scoped and measurable rather than broad or promotional."},
    {"key": "evidence", "label": "Evidence and substantiation", "weight": 25, "explanation": "Whether the claim can be supported by clear, recent and traceable evidence."},
    {"key": "scope", "label": "Scope and boundaries", "weight": 15, "explanation": "Whether the claim clearly defines the entity, workforce, suppliers, geographies and reporting period covered."},
    {"key": "assurance", "label": "Verification and control", "weight": 15, "explanation": "Whether the claim is supported by internal controls, review, audit or assurance."},
    {"key": "sensitivity", "label": "Stakeholder sensitivity", "weight": 15, "explanation": "Whether the topic concerns sensitive stakeholder impacts such as human rights, workers or vulnerable groups."},
    {"key": "misleading", "label": "Risk of misleading impression", "weight": 15, "explanation": "Whether the wording may overstate performance, coverage, control or outcomes."}
]

RULES = [
    {
        "triggers": ["people first", "put people first", "putting people first", "communities and society first", "society first"],
        "category": "Generic social responsibility claim",
        "risk": "Medium",
        "priority": "Medium term",
        "issue_type": "Generic social claim",
        "detected_issue": "The statement uses broad positive social wording without explaining what is covered, how performance is measured or which evidence supports the claim.",
        "risk_rationale": "This type of claim can create an impression of strong social performance while remaining too vague for users to verify. It should be linked to concrete policies, KPIs or outcomes.",
        "legal": "Potential social washing risk if presented as a general social-performance claim without substantiation.",
        "stakeholders": "Employees, customers, civil society, investors and regulators.",
        "evidence": "Employee engagement data, HR policies, grievance data, stakeholder engagement outcomes, employee well-being indicators and reporting references.",
        "rewrite": "We aim to strengthen employee well-being through annual engagement surveys, health and safety monitoring and targeted improvement plans.",
        "action": "Clarify the scope of the claim and add measurable social indicators or a reference to the relevant reporting section.",
        "scores": {"specificity": 55, "evidence": 60, "scope": 50, "assurance": 45, "sensitivity": 50, "misleading": 55}
    },
    {
        "triggers": ["committed to", "fully committed", "commitment to", "we support", "we aim to", "we expect", "we believe"],
        "category": "Commitment or aspiration claim",
        "risk": "Medium",
        "priority": "Medium term",
        "issue_type": "Unqualified commitment claim",
        "detected_issue": "The claim expresses an ambition or commitment but does not clearly distinguish between intention, policy, action plan and achieved result.",
        "risk_rationale": "Commitment claims are acceptable when framed as ambitions or policies. Risk increases when the wording implies that the outcome has already been achieved.",
        "legal": "Moderate risk if aspirational language is interpreted as a factual performance claim.",
        "stakeholders": "Employees, customers, investors, regulators and civil society.",
        "evidence": "Policy documents, targets, KPIs, governance responsibilities, implementation plans and progress reporting.",
        "rewrite": "We have adopted a policy and monitor implementation through defined responsibilities, progress reporting and improvement actions.",
        "action": "Clarify whether the statement refers to an ambition, policy, action plan or achieved result.",
        "scores": {"specificity": 45, "evidence": 55, "scope": 45, "assurance": 50, "sensitivity": 55, "misleading": 45}
    },
    {
        "triggers": ["human rights", "labour rights", "labor rights", "forced labour", "forced labor", "child labour", "child labor", "living wage", "modern slavery"],
        "category": "Human rights claim",
        "risk": "High",
        "priority": "Short term",
        "issue_type": "Sensitive human rights claim",
        "detected_issue": "The statement refers to human rights or labour rights, but the extracted text does not sufficiently evidence the due diligence process, scope or remediation approach.",
        "risk_rationale": "Human rights claims are sensitive because they relate to potentially severe impacts on affected people. A credible claim should be supported by due diligence, salient risk assessment, grievance mechanisms and follow-up evidence.",
        "legal": "High sensitivity due to sustainability reporting, human rights due diligence and supply-chain expectations.",
        "stakeholders": "Workers, suppliers, NGOs, regulators, investors and affected communities.",
        "evidence": "Human rights policy, due diligence process, salient risk assessment, grievance mechanism, remediation records and supplier assessments.",
        "rewrite": "We assess selected human rights risks through a risk-based due diligence process and follow up identified issues through corrective actions.",
        "action": "Add due diligence scope, salient risks, grievance channels and remediation process.",
        "scores": {"specificity": 70, "evidence": 80, "scope": 70, "assurance": 65, "sensitivity": 85, "misleading": 75}
    },
    {
        "triggers": ["entire value chain", "across our value chain", "all suppliers", "our suppliers respect", "suppliers respect", "highest labour standards", "highest labor standards", "responsible business conduct", "supplier code of conduct"],
        "category": "Value chain or supplier claim",
        "risk": "Very high",
        "priority": "Immediate",
        "issue_type": "Broad supplier or value-chain claim",
        "detected_issue": "The wording may imply broad control over suppliers or the full value chain, while the extracted text does not demonstrate full coverage or verification.",
        "risk_rationale": "Supplier and value-chain claims are high-risk when they suggest that all suppliers comply with certain standards. Companies usually have limited control over third parties and should use scoped, risk-based wording.",
        "legal": "Very sensitive where the claim implies complete supplier compliance or comprehensive control over external parties.",
        "stakeholders": "Suppliers, contracted workers, procurement teams, NGOs, customers, investors and regulators.",
        "evidence": "Supplier code of conduct, audit results, corrective action plans, coverage rate, risk segmentation and due diligence evidence.",
        "rewrite": "We require key suppliers to comply with our Supplier Code of Conduct and assess higher-risk suppliers through a risk-based due diligence process.",
        "action": "Replace absolute supplier wording with risk-based, scoped and evidence-backed language.",
        "scores": {"specificity": 85, "evidence": 90, "scope": 85, "assurance": 75, "sensitivity": 90, "misleading": 90}
    },
    {
        "triggers": ["diversity", "inclusion", "inclusive", "equality", "equal opportunities", "pay equity", "gender equality", "non-discrimination", "belonging"],
        "category": "Diversity, equality and inclusion claim",
        "risk": "Medium",
        "priority": "Medium term",
        "issue_type": "D&I claim requiring substantiation",
        "detected_issue": "The claim refers to diversity, equality or inclusion, but the extracted text does not clearly provide data, scope, baseline or progress evidence.",
        "risk_rationale": "D&I claims are often scrutinised because they can be perceived as reputational positioning. They should be connected to workforce data, policies, targets or concrete initiatives.",
        "legal": "D&I claims can attract scrutiny if the statement is not supported by data, policies or progress reporting.",
        "stakeholders": "Employees, candidates, customers, investors and advocacy groups.",
        "evidence": "Diversity metrics, inclusion survey results, pay equity analysis, policies, targets, action plans and governance ownership.",
        "rewrite": "We monitor diversity and inclusion through workforce data, employee feedback and targeted initiatives to improve representation and inclusion.",
        "action": "Add metrics, baseline year, scope and explanation of initiatives.",
        "scores": {"specificity": 55, "evidence": 65, "scope": 55, "assurance": 55, "sensitivity": 70, "misleading": 60}
    },
    {
        "triggers": ["ensure safe", "safe working conditions", "safe workplace", "health and safety", "well-being", "wellbeing", "engaging workplace", "employee wellbeing"],
        "category": "Health, safety and well-being claim",
        "risk": "High",
        "priority": "Short term",
        "issue_type": "Outcome or safety assurance claim",
        "detected_issue": "The wording may suggest that safe or positive working conditions are ensured, while the extracted text does not show the controls or performance data behind the statement.",
        "risk_rationale": "Safety and well-being claims are sensitive because they concern worker protection. Strong wording should be supported by KPIs, controls, incident data and improvement actions.",
        "legal": "Sensitive where claims imply guaranteed worker safety or broad coverage without measurable controls.",
        "stakeholders": "Employees, contractors, unions, regulators and insurers.",
        "evidence": "Incident rates, lost-time injury frequency rate, safety audits, training records, employee feedback and corrective actions.",
        "rewrite": "We monitor health and safety using incident reporting, training, risk assessments and targeted improvement measures.",
        "action": "Avoid guarantee-style wording and add measurable health and safety indicators.",
        "scores": {"specificity": 70, "evidence": 75, "scope": 65, "assurance": 65, "sensitivity": 75, "misleading": 80}
    },
    {
        "triggers": ["everyone", "all employees", "all workers", "for all", "highest", "best", "fully", "guarantee", "zero", "always", "never", "100%"],
        "category": "Absolute or broad wording",
        "risk": "High",
        "priority": "Short term",
        "issue_type": "Absolute wording",
        "detected_issue": "The claim contains broad or absolute wording that may overstate coverage, control or outcomes.",
        "risk_rationale": "Words such as 'all', 'fully', 'everyone', 'highest' or 'guarantee' create a high evidentiary burden. If full coverage cannot be demonstrated, the wording should be qualified.",
        "legal": "Absolute wording increases misrepresentation risk if the company cannot evidence complete coverage or outcomes.",
        "stakeholders": "Customers, employees, suppliers, investors, regulators and civil society.",
        "evidence": "Clear scope definition, coverage percentage, exceptions, methodology, assurance and evidence trail.",
        "rewrite": "Replace absolute wording with scoped, evidence-based language that explains what is covered and what remains in progress.",
        "action": "Remove absolute terms or qualify them with scope, limitations and evidence.",
        "scores": {"specificity": 80, "evidence": 80, "scope": 80, "assurance": 70, "sensitivity": 70, "misleading": 90}
    },
    {
        "triggers": ["training", "employee engagement", "responsible procurement", "sustainability reporting", "we report", "annual report", "assurance", "external audit", "audited"],
        "category": "Substantiation reference",
        "risk": "Low",
        "priority": "Monitor",
        "issue_type": "Potential evidence reference",
        "detected_issue": "The statement points to reporting or evidence, which can reduce risk if the underlying data is specific, accessible and current.",
        "risk_rationale": "References to reporting, training, assurance or procurement controls can support claims. However, the claim should still link clearly to the relevant data, period and scope.",
        "legal": "Lower risk where the statement points to measurable reporting, but evidence should be accessible and current.",
        "stakeholders": "Employees, investors, customers and auditors.",
        "evidence": "Sustainability report references, KPI tables, methodology notes, assurance statement, HR and procurement data.",
        "rewrite": "We report on selected workforce and procurement indicators, including training, employee engagement, diversity and responsible procurement metrics.",
        "action": "Link the claim to the relevant report section and specify the reporting period.",
        "scores": {"specificity": 25, "evidence": 35, "scope": 30, "assurance": 35, "sensitivity": 35, "misleading": 25}
    }
]


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = False
        self.parts = []
        self.skip_tags = {"script", "style", "noscript", "svg", "canvas", "form"}

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.skip_tags:
            self.skip = True

    def handle_endtag(self, tag):
        if tag.lower() in self.skip_tags:
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            text = " ".join(data.split())
            if len(text) > 2:
                self.parts.append(text)


def clean_visible_text(html):
    parser = VisibleTextParser()
    parser.feed(html)
    raw_text = "\n".join(parser.parts)
    lines, seen = [], set()
    for line in raw_text.splitlines():
        line = " ".join(line.split())
        low = line.lower()
        if len(line) > 2 and low not in seen:
            lines.append(line)
            seen.add(low)
    return "\n".join(lines)[:MAX_TEXT_CHARS]


def is_private_host(hostname):
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    try:
        for result in socket.getaddrinfo(hostname, None):
            ip = result[4][0]
            parsed = ipaddress.ip_address(ip)
            if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved:
                return True
    except Exception:
        return False
    return False


def fetch_url_text(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed.")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Invalid URL.")
    if is_private_host(parsed.hostname):
        raise ValueError("Private, local and internal URLs are blocked for safety.")

    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 SocialWashingScanHostable/6.0",
        "Accept": "text/html,application/xhtml+xml"
    })
    context = ssl.create_default_context()
    with urlopen(request, timeout=18, context=context) as response:
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ValueError("This URL does not seem to return an HTML page.")
        raw = response.read(2000000)
    html = raw.decode("utf-8", errors="ignore")
    return clean_visible_text(html)


def average(values):
    return round(sum(values) / len(values)) if values else 0


def snippet(text, trigger):
    lower = text.lower()
    idx = lower.find(trigger.lower())
    if idx < 0:
        return ""
    start = max(0, idx - 90)
    end = min(len(text), idx + len(trigger) + 150)
    return " ".join(text[start:end].split())


def risk_from_score(score):
    if score >= 76:
        return "Very high"
    if score >= 56:
        return "High"
    if score >= 31:
        return "Medium"
    return "Low"


def score_breakdown(findings):
    rows = []
    for criterion in SCORING_CRITERIA:
        values = [f["scores"].get(criterion["key"], 0) for f in findings]
        value = average(values) if values else 0
        rows.append({**criterion, "value": value, "weighted": round(value * criterion["weight"] / 100)})
    return rows


def build_finding_narrative(rule):
    return (
        "The detected wording falls under '" + rule["category"] + "'. "
        + rule["detected_issue"] + " "
        + rule["risk_rationale"] + " "
        + "Recommended correction: " + rule["action"]
    )


def conclusion_text(score, findings):
    if score >= 76:
        return "The analysed content contains high-sensitivity social washing risk signals. The main concern is that some claims may overstate social performance, supplier control or coverage without sufficient substantiation."
    if score >= 56:
        return "The analysed content contains several material social washing risk signals. The main improvement area is to qualify broad claims, clarify scope and strengthen the evidence trail."
    if score >= 31:
        return "The analysed content contains moderate social washing risk signals. Targeted improvements to wording, scope and substantiation are recommended before publication."
    return "The analysed content shows limited social washing risk signals based on the current rule-based review, but evidence and context should still be checked."


def executive_interpretation(score, findings):
    categories = []
    for f in findings:
        if f["category"] not in categories:
            categories.append(f["category"])
    cat_text = ", ".join(categories[:4]) if categories else "no clear category"
    if score >= 56:
        return "The scan indicates that the highest attention should go to: " + cat_text + ". The content should be reviewed by sustainability, legal/compliance and communications before external use."
    return "The scan identified the following areas for review: " + cat_text + ". The claims appear manageable if they are properly scoped and substantiated."


def top_priorities(findings):
    priorities = []
    for f in findings:
        if f["risk"] in ("Very high", "High") and len(priorities) < 3:
            priorities.append(f["recommended_action"])
    if not priorities:
        priorities = [
            "Document the evidence trail for each social claim.",
            "Clarify scope, reporting period and responsible owner.",
            "Review claims periodically to ensure they remain accurate."
        ]
    return priorities


def governance_actions(findings):
    actions = [
        "Create and maintain a register of social, labour, human rights, diversity and supplier claims.",
        "Assign claim ownership to sustainability, HR, procurement, legal and communications teams.",
        "Require evidence before publication, including scope, data source, methodology and date.",
        "Escalate high-risk claims about suppliers, human rights and diversity to legal/compliance review.",
        "Review claims periodically to ensure they remain accurate and substantiated."
    ]
    if any("supplier" in f["category"].lower() or "value chain" in f["category"].lower() for f in findings):
        actions.append("For supplier and value-chain claims, include supplier coverage, risk segmentation and corrective action evidence.")
    if any("human rights" in f["category"].lower() for f in findings):
        actions.append("For human rights claims, link the statement to due diligence, salient risk assessment, grievance mechanisms and remediation processes.")
    if any("diversity" in f["category"].lower() for f in findings):
        actions.append("For diversity and inclusion claims, include workforce data, scope, baseline year and progress indicators.")
    return actions


def rule_based_analyse(text, source_label):
    lower = text.lower()
    findings = []
    seen = set()

    for rule in RULES:
        hit = None
        for trigger in rule["triggers"]:
            if trigger.lower() in lower:
                hit = trigger
                break
        if not hit:
            continue

        key = rule["category"] + "-" + hit.lower()
        if key in seen:
            continue
        seen.add(key)

        numerical = average(list(rule["scores"].values()))
        findings.append({
            "detected_text": snippet(text, hit),
            "category": rule["category"],
            "risk": rule["risk"],
            "priority": rule["priority"],
            "issue_type": rule["issue_type"],
            "detected_issue": rule["detected_issue"],
            "risk_rationale": rule["risk_rationale"],
            "legal_sensitivity": rule["legal"],
            "stakeholders": rule["stakeholders"],
            "evidence_required": rule["evidence"],
            "recommended_action": rule["action"],
            "suggested_rewrite": rule["rewrite"],
            "scores": rule["scores"],
            "numerical_risk": numerical,
            "assessment_text": build_finding_narrative(rule)
        })

    if not findings:
        findings.append({
            "detected_text": text[:280] + ("..." if len(text) > 280 else ""),
            "category": "General social responsibility statement",
            "risk": "Low",
            "priority": "Monitor",
            "issue_type": "No major risk signal detected",
            "detected_issue": "The rule-based engine did not detect obvious high-risk social washing wording in the analysed text.",
            "risk_rationale": "This does not mean the claim is fully substantiated. It only means that the current wording does not trigger the main rule-based risk categories.",
            "legal_sensitivity": "Low based on current wording, but context and evidence should still be reviewed.",
            "stakeholders": "General stakeholders.",
            "evidence_required": "Policy documents, KPIs, governance responsibilities and reporting evidence.",
            "recommended_action": "Keep the claim specific, evidence-based and scoped.",
            "suggested_rewrite": "Use precise wording linked to measurable actions, reporting period and scope.",
            "scores": {"specificity": 20, "evidence": 25, "scope": 25, "assurance": 25, "sensitivity": 20, "misleading": 20},
            "numerical_risk": 23,
            "assessment_text": "No obvious high-risk wording was detected. A human review should still verify whether the claim is supported by appropriate evidence and whether the scope is clear."
        })

    findings = sorted(findings, key=lambda x: ({"Very high": 4, "High": 3, "Medium": 2, "Low": 1}.get(x["risk"], 0), x["numerical_risk"]), reverse=True)
    breakdown = score_breakdown(findings)
    overall_score = max(8, min(96, sum(row["weighted"] for row in breakdown)))
    if any(f["risk"] == "Very high" for f in findings):
        overall_score = max(overall_score, 76)

    immediate = sum(1 for f in findings if f["priority"] == "Immediate")
    high = sum(1 for f in findings if f["risk"] in ("High", "Very high"))

    return {
        "source_label": source_label,
        "engine": "structured_rule_based_v6",
        "analysis_date": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "overall_score": overall_score,
        "overall_risk": risk_from_score(overall_score),
        "score_breakdown": breakdown,
        "summary": {
            "finding_count": len(findings),
            "high_or_very_high_count": high,
            "immediate_priority_count": immediate,
            "main_conclusion": conclusion_text(overall_score, findings),
            "executive_interpretation": executive_interpretation(overall_score, findings),
            "top_priorities": top_priorities(findings)
        },
        "findings": findings,
        "governance_actions": governance_actions(findings),
        "disclaimer": "Indicative assessment only. Not legal advice and not a replacement for human rights due diligence, assurance or legal review.",
        "analysed_text_excerpt": text[:2500]
    }


def analyse(text, source_label, use_ai=False):
    # AI is intentionally not called in v6 to keep deployment reliable.
    # The UI keeps the checkbox for future extension, but rule-based output is structured and deterministic.
    return rule_based_analyse(text, source_label)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, content_type="text/html; charset=utf-8", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=200):
        self._send(json.dumps(data, ensure_ascii=False, indent=2), "application/json; charset=utf-8", status)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            frontend_path = APP_DIR / "frontend.html"
            self._send(frontend_path.read_text(encoding="utf-8"))
        elif self.path == "/api/health":
            self._send_json({"status": "ok", "version": "hostable_v6", "ai_configured": False})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw or "{}")

            if self.path == "/api/scan/text":
                text = data.get("text", "")
                if not text.strip():
                    self._send_json({"error": "No text provided"}, 400)
                    return
                self._send_json(analyse(text[:MAX_TEXT_CHARS], data.get("source_label", "Manual text input"), False))
                return

            if self.path == "/api/scan/url":
                url = data.get("url", "")
                if not url:
                    self._send_json({"error": "No URL provided"}, 400)
                    return
                text = fetch_url_text(url)
                self._send_json(analyse(text, url, False))
                return

            self._send_json({"error": "Unknown endpoint"}, 404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)


def main():
    print("Social Washing Scan Hostable v6")
    print(f"Serving on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
