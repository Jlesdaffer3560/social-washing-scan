#!/usr/bin/env python3
"""
Social Washing Scan - Hostable v8

Render-ready Python app using only standard library.
No references to third-party brand names. Compact report structure.
Sector and context risk are inferred by the tool from URL, company name, sector hints and scanned text.
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
import re

PORT = int(os.environ.get("PORT", "8000"))
HOST = "0.0.0.0"
MAX_TEXT_CHARS = 60000
APP_DIR = Path(__file__).resolve().parent

BENCHMARKS = [
    "EU consumer-protection rules on misleading sustainability-related claims",
    "CSRD / ESRS S1-S4: own workforce, workers in the value chain, affected communities, consumers and end-users",
    "Human-rights due-diligence expectations under UNGPs, OECD Guidelines and CSDDD logic",
    "ILO fundamental labour-rights principles",
    "GRI-style reporting quality: balance, comparability, evidence, management approach and corrective actions"
]

SECTOR_LIBRARY = [
    {
        "level": "High",
        "score": 14,
        "terms": ["fast fashion", "apparel", "textile retail", "garment", "fashion", "clothing", "discount retail", "discount food", "supermarket", "grocery", "food retail", "catering", "facilities", "outsourced", "platform", "delivery", "gig", "commodity", "cocoa", "palm oil", "coffee", "cotton"],
        "explanation": "The business model may involve structurally higher exposure to low-wage work, complex supply chains, migrant/seasonal labour, supplier pressure, vulnerable consumers or worker-rights issues."
    },
    {
        "level": "Medium",
        "score": 8,
        "terms": ["bank", "finance", "insurance", "telecom", "digital", "aviation", "airline", "transport", "chemical", "energy", "infrastructure", "manufacturing", "industrial", "food ingredients", "technology", "utility", "gas", "logistics"],
        "explanation": "The sector has meaningful social exposure, but risk depends strongly on claim type, geography, outsourcing, value-chain exposure, customer impacts and company context."
    },
    {
        "level": "Low",
        "score": 3,
        "terms": ["software", "consulting", "professional services", "design studio", "office services"],
        "explanation": "The sector appears to have lower structural social-washing exposure, although broad social claims still require evidence."
    }
]

KNOWN_COMPANY_HINTS = {
    "kbc": {
        "company": "KBC",
        "sector": "Banking and financial services",
        "sector_level": "Medium",
        "context_level": "Medium",
        "context_note": "Responsible-finance, customer-protection, inclusion and human-rights-due-diligence claims can be sensitive because financing and investment decisions have indirect social impacts."
    },
    "delhaize": {
        "company": "Delhaize",
        "sector": "Food retail and supermarkets",
        "sector_level": "High",
        "context_level": "High",
        "context_note": "Food retail can involve franchise/associate labour, supplier pressure, farm-labour exposure, affordability claims and value-chain human-rights risks."
    },
    "aldi": {
        "company": "Aldi",
        "sector": "Discount food retail",
        "sector_level": "High",
        "context_level": "High",
        "context_note": "Discount food retail has heightened exposure to purchasing practices, agricultural supply chains, migrant/seasonal labour and broad responsible-sourcing claims."
    },
    "lidl": {
        "company": "Lidl",
        "sector": "Discount food retail",
        "sector_level": "High",
        "context_level": "High",
        "context_note": "Discount food retail has heightened exposure to purchasing practices, agricultural supply chains, migrant/seasonal labour and broad responsible-sourcing claims."
    },
    "zara": {
        "company": "Zara / Inditex",
        "sector": "Fast fashion and apparel retail",
        "sector_level": "High",
        "context_level": "Very high",
        "context_note": "Fast fashion and apparel supply chains are highly exposed to labour-rights, subcontracting, audit-quality, wage, traceability and worker-voice issues."
    },
    "inditex": {
        "company": "Inditex / Zara",
        "sector": "Fast fashion and apparel retail",
        "sector_level": "High",
        "context_level": "Very high",
        "context_note": "Fast fashion and apparel supply chains are highly exposed to labour-rights, subcontracting, audit-quality, wage, traceability and worker-voice issues."
    },
    "fluxys": {
        "company": "Fluxys",
        "sector": "Gas infrastructure and energy transport",
        "sector_level": "Medium",
        "context_level": "Medium",
        "context_note": "Energy infrastructure has exposure to safety, contractor management, communities, emergency preparedness, procurement and transition-related claims."
    },
    "sodexo": {
        "company": "Sodexo",
        "sector": "Catering, facilities management and outsourced services",
        "sector_level": "High",
        "context_level": "High",
        "context_note": "Outsourced catering and facilities work can involve frontline labour, low-margin contracts, contractor coverage, migrant workers, workload and wage risks."
    },
    "bnp": {
        "company": "BNP Paribas / Fortis",
        "sector": "Banking and sustainable finance",
        "sector_level": "Medium",
        "context_level": "High",
        "context_note": "Responsible-finance and human-rights claims are sensitive because lending and investment decisions can be connected to high-risk sectors or geographies."
    },
    "proximus": {
        "company": "Proximus",
        "sector": "Telecommunications and digital services",
        "sector_level": "Medium",
        "context_level": "Medium",
        "context_note": "Telecom social claims may concern digital inclusion, vulnerable consumers, privacy, cybersecurity, supply-chain labour and responsible digitalisation."
    }
}

CONTEXT_TERMS = [
    ("Very high", 24, ["forced labour", "forced labor", "child labour", "child labor", "modern slavery", "xinjiang", "uyghur", "living wage", "migrant workers", "low wages", "discrimination lawsuit", "human rights complaint"]),
    ("High", 18, ["strike", "labour dispute", "labor dispute", "union", "grievance", "ncp complaint", "lawsuit", "ngo report", "allegation", "controversy", "remediation", "supplier non-compliance", "audit failure"]),
    ("Medium", 10, ["complaint", "accessibility", "vulnerable customers", "contractor", "subcontractor", "affected communities", "privacy incident", "restructuring", "franchise"]),
    ("Low", 4, ["policy", "training", "reporting", "audit", "assurance", "supplier code"])
]

RULES = [
    {
        "triggers": ["people first", "positive impact", "social impact", "support society", "communities and society", "better for everyone", "social value"],
        "claim_type": "Broad social-impact claim",
        "risk": "Medium",
        "benchmark": "Misleading-claims rules; ESRS S1/S3/S4; GRI-style reporting quality",
        "esrs": "ESRS S1/S3/S4 depending on affected stakeholder group",
        "stakeholder": "Employees, customers, communities or society at large",
        "issue": "The wording suggests positive social outcomes but does not define scope, affected groups, metrics or evidence.",
        "rationale": "Broad social-impact language can overstate outcomes if it is not linked to measurable actions, targets, results and limitations.",
        "evidence": "Defined stakeholder group, policy/action, KPI, baseline, target, reporting period, limitations and progress evidence.",
        "rewrite": "We report selected social indicators for defined stakeholder groups and disclose progress against specific actions and targets.",
        "severity": 12,
        "gap": 13,
        "vulnerability": 6
    },
    {
        "triggers": ["ethical", "fair", "responsible", "trusted", "socially responsible", "socially sustainable", "caring", "worker-friendly"],
        "claim_type": "Broad ethical or responsible-business claim",
        "risk": "High",
        "benchmark": "Misleading-claims rules; OECD due diligence; UNGPs; GRI-style evidence requirements",
        "esrs": "Cross-cutting; often ESRS S1/S2/S3/S4",
        "stakeholder": "Consumers, workers, value-chain workers, communities or customers",
        "issue": "The claim reassures users about responsible conduct but does not specify what is covered or how it is verified.",
        "rationale": "Generic ethical or responsible-business claims carry a high evidence burden because they can influence trust, purchasing or investment decisions.",
        "evidence": "Claim-specific evidence, scope, criteria, exclusions, due-diligence process, independent verification, grievance channels and remediation outcomes.",
        "rewrite": "We apply defined responsible-business criteria to specific activities and disclose scope, methodology, limitations and progress.",
        "severity": 18,
        "gap": 16,
        "vulnerability": 9
    },
    {
        "triggers": ["human rights", "labour rights", "labor rights", "decent work", "forced labour", "forced labor", "child labour", "child labor", "living wage", "modern slavery"],
        "claim_type": "Human-rights or fundamental labour-rights claim",
        "risk": "High",
        "benchmark": "UNGPs; OECD Guidelines; ILO principles; due-diligence expectations; ESRS S1/S2",
        "esrs": "ESRS S1 Own workforce / ESRS S2 Workers in the value chain",
        "stakeholder": "Own workers, value-chain workers, vulnerable workers or affected communities",
        "issue": "The statement refers to human or labour rights but may not evidence due diligence, salient risks, tracking, grievance access or remedy.",
        "rationale": "Human-rights claims are sensitive because they relate to potentially severe impacts on affected people.",
        "evidence": "Human-rights policy, salient-risk assessment, due-diligence steps, stakeholder engagement, grievance mechanism, tracking and remedy evidence.",
        "rewrite": "We assess selected human-rights risks through a risk-based due-diligence process and follow up identified issues through corrective actions.",
        "severity": 21,
        "gap": 17,
        "vulnerability": 13
    },
    {
        "triggers": ["supply chain", "value chain", "all suppliers", "supplier", "responsible sourcing", "ethical sourcing", "audited", "certified", "traceable", "supplier code"],
        "claim_type": "Supply-chain or supplier-responsibility claim",
        "risk": "High",
        "benchmark": "Due-diligence expectations; UNGPs; OECD Guidelines; ILO principles; ESRS S2",
        "esrs": "ESRS S2 Workers in the value chain",
        "stakeholder": "Supplier workers, contractors, migrant/seasonal workers, farmers or communities",
        "issue": "The wording may imply control over suppliers or a responsible value chain without demonstrating coverage, verification quality or remediation.",
        "rationale": "Supplier claims are high risk where supplier tiers, audit quality, worker voice and corrective-action closure are unclear.",
        "evidence": "Supplier-tier scope, supplier code, audit methodology, worker interviews, non-compliance cases, corrective-action closure rate, grievance channels and limits of certification.",
        "rewrite": "We assess higher-risk suppliers through a risk-based process and disclose coverage, findings and corrective-action progress.",
        "severity": 22,
        "gap": 18,
        "vulnerability": 13
    },
    {
        "triggers": ["diversity", "inclusion", "inclusive", "equality", "equal opportunities", "pay equity", "gender equality", "non-discrimination", "belonging"],
        "claim_type": "Diversity, equality and inclusion claim",
        "risk": "Medium",
        "benchmark": "ESRS S1; ILO non-discrimination principle; GRI; misleading-claims rules",
        "esrs": "ESRS S1 Own workforce",
        "stakeholder": "Employees, candidates, customers or affected groups",
        "issue": "The claim refers to diversity, equality or inclusion but may not provide data, scope, baseline or progress evidence.",
        "rationale": "D&I claims can become reputationally sensitive if they are not supported by workforce data, targets or concrete actions.",
        "evidence": "Workforce diversity metrics, pay-equity data, baseline, targets, inclusion survey, action plan and governance owner.",
        "rewrite": "We monitor diversity and inclusion using workforce data, employee feedback and targeted initiatives, with progress disclosed for the reporting period.",
        "severity": 14,
        "gap": 14,
        "vulnerability": 8
    },
    {
        "triggers": ["safe workplace", "safe working", "health and safety", "well-being", "wellbeing", "worker welfare", "quality of life", "care for employees"],
        "claim_type": "Health, safety or worker-welfare claim",
        "risk": "High",
        "benchmark": "ILO safe and healthy work principle; ESRS S1; GRI; misleading-claims rules",
        "esrs": "ESRS S1 Own workforce",
        "stakeholder": "Own workers, contractors and outsourced workers",
        "issue": "The wording suggests safe or positive working conditions but may not show controls, KPIs or outcome data.",
        "rationale": "Worker-welfare claims concern worker protection and require evidence on actual conditions, incidents, workload and remedy.",
        "evidence": "Incident rates, LTIFR, contractor coverage, safety audits, worker feedback, workload data, grievance cases and corrective actions.",
        "rewrite": "We monitor worker health and safety through incident reporting, training, risk assessments and corrective actions covering employees and relevant contractors.",
        "severity": 18,
        "gap": 15,
        "vulnerability": 11
    },
    {
        "triggers": ["accessibility", "vulnerable customers", "customer care", "fair treatment", "customer protection", "affordable for all", "financial inclusion", "digital inclusion"],
        "claim_type": "Customer welfare, accessibility or inclusion claim",
        "risk": "Medium",
        "benchmark": "ESRS S4; misleading-claims rules; GRI customer-impact reporting",
        "esrs": "ESRS S4 Consumers and end-users",
        "stakeholder": "Consumers, end-users, vulnerable customers or passengers",
        "issue": "The claim concerns customer welfare but may not show measurable outcomes, limitations, complaints or remedy.",
        "rationale": "Claims about inclusion, accessibility and care can be misleading if vulnerable groups, affordability, complaints and remedy are not addressed.",
        "evidence": "Accessibility metrics, complaints, remedy process, vulnerable-customer safeguards, incident data, affordability criteria and service-quality outcomes.",
        "rewrite": "We track customer inclusion and accessibility through defined metrics, complaint handling and improvement actions for identified vulnerable groups.",
        "severity": 14,
        "gap": 13,
        "vulnerability": 10
    },
    {
        "triggers": ["community", "good neighbour", "affected communities", "local value", "community support", "enabling society"],
        "claim_type": "Community impact or social-value claim",
        "risk": "Medium",
        "benchmark": "ESRS S3; UNGPs; OECD due diligence; GRI",
        "esrs": "ESRS S3 Affected communities",
        "stakeholder": "Affected communities, local residents or civil society",
        "issue": "The claim suggests positive community value but may not show impact measurement, stakeholder engagement or grievance access.",
        "rationale": "Community-impact claims should show both positive contribution and management of adverse impacts.",
        "evidence": "Stakeholder engagement, impact assessment, community KPIs, grievance channels, remediation actions and limitations.",
        "rewrite": "We engage with affected communities and disclose the scope, outcomes and limitations of our community-impact actions.",
        "severity": 15,
        "gap": 14,
        "vulnerability": 9
    },
    {
        "triggers": ["everyone", "all employees", "all workers", "all suppliers", "for all", "highest", "best", "fully", "guarantee", "zero", "always", "never", "100%"],
        "claim_type": "Absolute or broad wording",
        "risk": "High",
        "benchmark": "Misleading-claims rules; reporting quality principles",
        "esrs": "Cross-cutting claim-quality issue",
        "stakeholder": "All stakeholders mentioned or implied by the claim",
        "issue": "The claim contains absolute wording that may overstate coverage, control or outcomes.",
        "rationale": "Words such as all, fully, highest or guarantee create a high evidentiary burden and can mislead if exceptions or limitations exist.",
        "evidence": "Coverage percentage, scope, exceptions, methodology, assurance, limitations and evidence trail.",
        "rewrite": "Replace absolute wording with scoped, evidence-based wording that explains what is covered and what remains in progress.",
        "severity": 19,
        "gap": 16,
        "vulnerability": 8
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
            clean = " ".join(data.split())
            if len(clean) > 2:
                self.parts.append(clean)


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
            parsed = ipaddress.ip_address(result[4][0])
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
        "User-Agent": "Mozilla/5.0 SocialWashingScanHostable/8.0",
        "Accept": "text/html,application/xhtml+xml"
    })
    context = ssl.create_default_context()
    with urlopen(request, timeout=18, context=context) as response:
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ValueError("This URL does not seem to return an HTML page.")
        raw = response.read(2000000)
    return clean_visible_text(raw.decode("utf-8", errors="ignore"))


def score_to_level(score):
    if score >= 75:
        return "Very high"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


def level_to_context_score(level):
    return {"None": 0, "Low": 4, "Medium": 10, "High": 18, "Very high": 24}.get(level, 0)


def snippet(text, trigger):
    lower = text.lower()
    idx = lower.find(trigger.lower())
    if idx < 0:
        return ""
    start = max(0, idx - 90)
    end = min(len(text), idx + len(trigger) + 160)
    return " ".join(text[start:end].split())


def infer_company_from_url_or_text(source_label, text):
    combined = ((source_label or "") + " " + (text or "")[:3000]).lower()
    for key, profile in KNOWN_COMPANY_HINTS.items():
        if key in combined:
            return profile
    hostname = ""
    try:
        hostname = urlparse(source_label).hostname or ""
        name = hostname.split(".")[-2] if "." in hostname else hostname
        if name and len(name) > 2:
            return {"company": name.title(), "sector": "Not automatically identified", "sector_level": "Medium", "context_level": "None", "context_note": "No known profile matched; sector and context were inferred from text."}
    except Exception:
        pass
    return {"company": "Company / page reviewed", "sector": "Not automatically identified", "sector_level": "Medium", "context_level": "None", "context_note": "No known profile matched; sector and context were inferred from text."}


def infer_sector(text, profile):
    combined = (profile.get("sector", "") + " " + text[:5000]).lower()
    if profile.get("sector_level") and profile.get("sector_level") != "Medium":
        level = profile["sector_level"]
        match = "known company/sector profile"
    else:
        best = None
        for candidate in SECTOR_LIBRARY:
            hits = [term for term in candidate["terms"] if term in combined]
            if hits:
                best = (candidate, hits)
                break
        if best:
            level = best[0]["level"]
            match = ", ".join(best[1][:4])
        else:
            level = profile.get("sector_level", "Medium")
            match = "default medium exposure"
    chosen = next(s for s in SECTOR_LIBRARY if s["level"] == level)
    return {"level": level, "score": chosen["score"], "explanation": chosen["explanation"], "basis": match}


def infer_context(text, profile):
    combined = (profile.get("context_note", "") + " " + text[:10000]).lower()
    profile_level = profile.get("context_level", "None")
    best_level = profile_level
    best_score = level_to_context_score(profile_level)
    matches = []
    for level, score, terms in CONTEXT_TERMS:
        found = [t for t in terms if t in combined]
        if found and score > best_score:
            best_level = level
            best_score = score
            matches = found[:5]
        elif found:
            matches.extend(found[:3])
    explanation = profile.get("context_note", "")
    if matches:
        explanation = (explanation + " " if explanation else "") + "Detected context signals: " + ", ".join(sorted(set(matches))[:6]) + "."
    if not explanation:
        explanation = "No clear controversy or high-sensitivity context was detected from the scanned text; this is not an independent controversy search."
    return {"level": best_level, "score": best_score, "explanation": explanation}


def detect_claims(text):
    lower = text.lower()
    findings = []
    seen = set()
    for rule in RULES:
        trigger = next((t for t in rule["triggers"] if t.lower() in lower), None)
        if not trigger:
            continue
        key = rule["claim_type"] + trigger.lower()
        if key in seen:
            continue
        seen.add(key)
        finding_score = min(100, round((rule["severity"]/25*35) + (rule["gap"]/20*30) + (rule["vulnerability"]/15*20) + (15 if rule["risk"] == "High" else 8 if rule["risk"] == "Medium" else 3)))
        findings.append({
            "claim": snippet(text, trigger),
            "trigger": trigger,
            "claim_type": rule["claim_type"],
            "risk": rule["risk"],
            "benchmark": rule["benchmark"],
            "esrs_mapping": rule["esrs"],
            "stakeholder_group": rule["stakeholder"],
            "detected_issue": rule["issue"],
            "risk_rationale": rule["rationale"],
            "evidence_gap": rule["evidence"],
            "suggested_rewrite": rule["rewrite"],
            "claim_score": finding_score,
            "subscores": {
                "claim_severity": rule["severity"],
                "evidence_gap": rule["gap"],
                "stakeholder_vulnerability": rule["vulnerability"]
            },
            "remediation_status": "Open - requires substantiation review",
            "assessment_text": "The detected wording is a " + rule["claim_type"].lower() + ". " + rule["issue"] + " " + rule["rationale"]
        })
    if not findings:
        findings.append({
            "claim": text[:280] + ("..." if len(text) > 280 else ""),
            "trigger": "",
            "claim_type": "No major social-washing keyword detected",
            "risk": "Low",
            "benchmark": "General claim-quality review",
            "esrs_mapping": "Not mapped",
            "stakeholder_group": "General stakeholders",
            "detected_issue": "No obvious high-risk social-washing wording was detected by the rule-based scan.",
            "risk_rationale": "This does not confirm that the claim is fully substantiated; it only means no major rule-based risk signal was detected.",
            "evidence_gap": "Evidence and context should still be checked manually.",
            "suggested_rewrite": "Use precise wording linked to measurable actions, reporting period and scope.",
            "claim_score": 18,
            "subscores": {"claim_severity": 4, "evidence_gap": 6, "stakeholder_vulnerability": 3},
            "remediation_status": "Monitor",
            "assessment_text": "No obvious high-risk social-washing wording was detected. Manual review remains recommended."
        })
    return sorted(findings, key=lambda f: f["claim_score"], reverse=True)


def component_scores(findings, sector, context):
    max_severity = max(f["subscores"]["claim_severity"] for f in findings)
    max_gap = max(f["subscores"]["evidence_gap"] for f in findings)
    max_vuln = max(f["subscores"]["stakeholder_vulnerability"] for f in findings)
    return {
        "claim_severity": min(25, max_severity),
        "evidence_gap": min(20, max_gap),
        "context": min(25, context["score"]),
        "stakeholder_vulnerability": min(15, max_vuln),
        "sector_modifier": min(15, sector["score"])
    }


def build_assessment(profile, sector, context, findings, components, final_score):
    company = profile["company"]
    sector_name = profile.get("sector", "Inferred sector")
    flags = sorted(set(f["trigger"] for f in findings if f.get("trigger")))
    topic_types = sorted(set(f["claim_type"] for f in findings))
    high_findings = [f for f in findings if f["risk"] == "High"]
    level = score_to_level(final_score)

    if high_findings:
        conclusion = f"{level} risk. {company} should avoid broad social, ethical or responsibility claims unless they are specific, time-bound and supported by evidence on scope, due diligence, affected stakeholders, grievance channels and remediation."
    else:
        conclusion = f"{level} risk. {company} should keep social claims specific, scoped and supported by clear evidence, while documenting limitations and reporting boundaries."

    analysis = (
        f"The scan identified {len(findings)} social-claim signal(s), mainly linked to "
        + (", ".join(topic_types[:4]) if topic_types else "general claim quality")
        + ". The final score combines the claim wording, evidence gap, inferred sector exposure, stakeholder vulnerability and automatically inferred context sensitivity. "
        + "The result should be read as a prioritisation signal, not as a legal finding."
    )

    driver_parts = []
    if components["claim_severity"] >= 18:
        driver_parts.append("strong or broad claim wording")
    if components["evidence_gap"] >= 15:
        driver_parts.append("significant evidence gap")
    if components["sector_modifier"] >= 12:
        driver_parts.append("high sector exposure")
    if components["context"] >= 18:
        driver_parts.append("heightened controversy/context sensitivity")
    if components["stakeholder_vulnerability"] >= 11:
        driver_parts.append("vulnerable stakeholder exposure")
    main_driver = ", ".join(driver_parts) if driver_parts else "moderate claim and context exposure"

    return {
        "company": company,
        "inferred_sector": sector_name,
        "inferred_sector_risk": sector["level"],
        "sector_basis": sector["basis"],
        "inferred_context_level": context["level"],
        "context_explanation": context["explanation"],
        "final_result": f"{level} social-washing risk; risk score {final_score}/100.",
        "short_summary": f"Risk is driven by {main_driver}.",
        "benchmarks_used": "; ".join(BENCHMARKS),
        "topics_detected": ", ".join(topic_types) if topic_types else "No major claim category detected",
        "analysis": analysis,
        "main_score_driver": main_driver,
        "potential_flags": "; ".join(flags) if flags else "No major keyword flag detected.",
        "conclusion": conclusion
    }


def analyse(text, source_label):
    profile = infer_company_from_url_or_text(source_label, text)
    sector = infer_sector(text, profile)
    context = infer_context(text, profile)
    findings = detect_claims(text)
    components = component_scores(findings, sector, context)
    final_score = min(100, sum(components.values()))
    level = score_to_level(final_score)
    assessment = build_assessment(profile, sector, context, findings, components, final_score)

    return {
        "version": "hostable_v8",
        "source_label": source_label,
        "analysis_date": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "overall_score": final_score,
        "overall_risk": level,
        "sector": sector,
        "context": context,
        "scoring_components": [
            {"key": "claim_severity", "label": "Claim severity", "score": components["claim_severity"], "max": 25, "description": "Strength, breadth and sensitivity of detected social claims."},
            {"key": "evidence_gap", "label": "Evidence gap", "score": components["evidence_gap"], "max": 20, "description": "Extent to which the claim lacks clear scope, metrics, methodology or proof."},
            {"key": "context", "label": "Inferred company/context sensitivity", "score": components["context"], "max": 25, "description": "Sensitivity inferred from known profile and scanned controversy/context signals."},
            {"key": "stakeholder_vulnerability", "label": "Stakeholder vulnerability / remedy gap", "score": components["stakeholder_vulnerability"], "max": 15, "description": "Exposure to workers, value-chain workers, vulnerable consumers or affected communities."},
            {"key": "sector_modifier", "label": "Inferred sector modifier", "score": components["sector_modifier"], "max": 15, "description": "Structural exposure inferred from sector and scanned text."}
        ],
        "assessment": assessment,
        "findings": findings,
        "export_fields": ["company", "URL/source", "claim", "claim type", "stakeholder group", "benchmark", "ESRS mapping", "evidence gap", "score", "rationale", "suggested rewrite", "remediation status"],
        "disclaimer": "This is an indicative first-pass assessment, not a legal finding. A high score means that the sector, claims or public context require stronger substantiation; it does not mean that the company has committed social washing.",
        "analysed_text_excerpt": text[:2500]
    }


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
            self._send((APP_DIR / "frontend.html").read_text(encoding="utf-8"))
        elif self.path == "/api/health":
            self._send_json({"status": "ok", "version": "hostable_v8"})
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
                self._send_json(analyse(text[:MAX_TEXT_CHARS], data.get("source_label", "Manual text input")))
                return

            if self.path == "/api/scan/url":
                url = data.get("url", "")
                if not url:
                    self._send_json({"error": "No URL provided"}, 400)
                    return
                text = fetch_url_text(url)
                self._send_json(analyse(text, url))
                return

            self._send_json({"error": "Unknown endpoint"}, 404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)


def main():
    print("Social Washing Scan Hostable v8")
    print(f"Serving on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
