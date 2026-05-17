#!/usr/bin/env python3
"""
Social Washing Scan - Hostable v5

Single-file Python web app using only Python standard library.
- Serves frontend at /
- API for text scan and URL scan
- Optional OpenAI analysis via OPENAI_API_KEY environment variable
- Designed for local use and simple public hosting, e.g. Render Web Service

Start locally:
    python app.py

Environment variables:
    PORT=8000
    OPENAI_API_KEY=optional
    OPENAI_MODEL=gpt-5-mini
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser
import json
import os
import ssl
import re
import socket
import ipaddress
import datetime

PORT = int(os.environ.get("PORT", "8000"))
HOST = "0.0.0.0"
MAX_TEXT_CHARS = 60000
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")


# Enrich rule outputs with more structured, report-style wording.
for _rule in RULES:
    _rule.setdefault("issue_type", _rule.get("category", "Detected claim issue"))
    _rule.setdefault("detected_issue", _rule.get("issue", "Potentially insufficiently substantiated social claim."))
    _rule.setdefault("risk_rationale", _rule.get("legal", "The claim may create a misleading impression if not properly substantiated."))

SCORING_CRITERIA = [
    {"key": "specificity", "label": "Claim specificity", "weight": 15, "explanation": "Assesses whether the claim is precise, measurable and clearly formulated."},
    {"key": "evidence", "label": "Evidence quality", "weight": 25, "explanation": "Assesses whether the claim appears supported by data, documents, controls or audit evidence."},
    {"key": "scope", "label": "Scope clarity", "weight": 15, "explanation": "Assesses whether boundaries are clear: entity, workforce, supplier tier, geography and period."},
    {"key": "assurance", "label": "Verification / assurance", "weight": 15, "explanation": "Assesses whether independent review, audit or internal control evidence is referenced."},
    {"key": "sensitivity", "label": "Stakeholder sensitivity", "weight": 15, "explanation": "Assesses whether the claim relates to sensitive stakeholder issues such as human rights or workers."},
    {"key": "misleading", "label": "Misleading impression risk", "weight": 15, "explanation": "Assesses whether the wording could overstate performance, control or coverage."}
]

RULES = [
    {
        "triggers": ["people first", "put people first", "putting people first", "communities and society first", "society first"],
        "category": "Generic social responsibility claim",
        "risk": "Medium",
        "priority": "Medium term",
        "issue": "Broad social wording without clear scope, boundary or substantiation.",
        "legal": "Potential social washing risk if presented as a general social-performance claim without evidence.",
        "stakeholders": "Employees, customers, civil society, investors and regulators.",
        "evidence": "Employee data, stakeholder engagement outcomes, HR policies, grievance data, external benchmarks and reporting references.",
        "rewrite": "We aim to strengthen employee well-being through annual engagement surveys, health and safety monitoring and targeted improvement plans.",
        "action": "Add a clear scope and link the claim to measurable employee or stakeholder indicators.",
        "scores": {"specificity": 55, "evidence": 60, "scope": 50, "assurance": 45, "sensitivity": 50, "misleading": 55}
    },
    {
        "triggers": ["committed to", "fully committed", "commitment to", "we support", "we aim to", "we expect", "we believe"],
        "category": "Commitment or aspiration claim",
        "risk": "Medium",
        "priority": "Medium term",
        "issue": "Commitment wording is acceptable, but it should not imply achieved performance unless supported by evidence.",
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
        "issue": "Human rights claims are sensitive and require evidence of due diligence, scope, salient risks and remediation mechanisms.",
        "legal": "High sensitivity due to sustainability reporting, human rights due diligence and supply-chain expectations.",
        "stakeholders": "Workers, suppliers, NGOs, regulators, investors and affected communities.",
        "evidence": "Human rights policy, due diligence process, salient risk assessment, grievance mechanism, remediation records and supplier assessments.",
        "rewrite": "We assess selected human rights risks through a risk-based due diligence process and follow up identified issues through corrective actions.",
        "action": "Add details on due diligence scope, salient risks, grievance channels and remediation process.",
        "scores": {"specificity": 70, "evidence": 80, "scope": 70, "assurance": 65, "sensitivity": 85, "misleading": 75}
    },
    {
        "triggers": ["entire value chain", "across our value chain", "all suppliers", "our suppliers respect", "suppliers respect", "highest labour standards", "highest labor standards", "responsible business conduct", "supplier code of conduct"],
        "category": "Value chain or supplier claim",
        "risk": "Very high",
        "priority": "Immediate",
        "issue": "Supplier or value-chain wording may imply broad control over third parties or full value-chain coverage.",
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
        "issue": "Diversity and inclusion claims require scope clarity and supporting workforce data.",
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
        "issue": "Safety and well-being wording can imply guaranteed outcomes and should be linked to measurable controls.",
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
        "issue": "Absolute or very broad wording can overstate actual control, coverage or outcomes.",
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
        "issue": "This may support substantiation, but the claim should link to concrete data and reporting boundaries.",
        "legal": "Lower risk where the statement points to measurable reporting, but evidence should be accessible and current.",
        "stakeholders": "Employees, investors, customers and auditors.",
        "evidence": "Sustainability report references, KPI tables, methodology notes, assurance statement, HR and procurement data.",
        "rewrite": "We report on selected workforce and procurement indicators, including training, employee engagement, diversity and responsible procurement metrics.",
        "action": "Link the claim to the relevant report section and specify the reporting period.",
        "scores": {"specificity": 25, "evidence": 35, "scope": 30, "assurance": 35, "sensitivity": 35, "misleading": 25}
    }
]

FRONTEND_HTML = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8"/>\n<title>Social Washing Scan</title>\n<meta name="viewport" content="width=device-width, initial-scale=1"/>\n<style>\n:root {\n  --bg:#f6f7fb; --surface:#ffffff; --text:#172033; --muted:#667085; --border:#d0d5dd;\n  --brand:#1f3a5f; --brand2:#2d5d8c; --light:#eef4ff;\n  --green-bg:#dcfce7; --green:#166534; --yellow-bg:#fef9c3; --yellow:#854d0e;\n  --orange-bg:#ffedd5; --orange:#9a3412; --red-bg:#fee2e2; --red:#991b1b;\n}\n* { box-sizing:border-box; }\nbody { font-family: Inter, Arial, sans-serif; background:var(--bg); color:var(--text); margin:0; }\nheader { background:linear-gradient(135deg, var(--brand), var(--brand2)); color:white; padding:30px 32px; }\n.header-inner { max-width:1220px; margin:0 auto; display:flex; justify-content:space-between; gap:24px; align-items:flex-start; }\nh1 { margin:0; font-size:32px; letter-spacing:-.4px; }\nh2 { margin:0 0 14px; font-size:20px; }\nh3 { margin:18px 0 8px; font-size:16px; }\np { line-height:1.55; }\nmain { max-width:1220px; margin:0 auto; padding:28px; }\n.card { background:var(--surface); border:1px solid var(--border); border-radius:18px; padding:22px; margin-bottom:22px; box-shadow:0 4px 14px rgba(16,24,40,.06); }\n.grid { display:grid; grid-template-columns:1fr 1fr; gap:22px; }\n.grid3 { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }\n.grid4 { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }\ntextarea,input { width:100%; border:1px solid var(--border); border-radius:14px; padding:12px; font:inherit; background:white; }\ntextarea { min-height:230px; }\nlabel { font-weight:700; display:block; margin:12px 0 7px; }\nbutton { border:0; background:var(--brand); color:white; border-radius:14px; padding:10px 14px; font-weight:800; cursor:pointer; margin:4px 6px 4px 0; }\nbutton.secondary { background:white; color:var(--brand); border:1px solid var(--border); }\nbutton:hover { opacity:.92; }\nbutton:disabled { opacity:.5; cursor:not-allowed; }\n.status { border-left:5px solid var(--brand2); }\n.score { font-size:68px; line-height:1; font-weight:900; letter-spacing:-2px; }\n.badge { display:inline-block; border-radius:999px; padding:6px 11px; font-size:12px; font-weight:900; white-space:nowrap; }\n.low { background:var(--green-bg); color:var(--green); }\n.medium { background:var(--yellow-bg); color:var(--yellow); }\n.high { background:var(--orange-bg); color:var(--orange); }\n.veryhigh { background:var(--red-bg); color:var(--red); }\n.kpi { background:#f8fafc; border:1px solid #e4e7ec; border-radius:16px; padding:14px; }\n.kpi strong { font-size:24px; }\n.muted { color:var(--muted); }\n.small { font-size:13px; }\ntable { width:100%; border-collapse:collapse; font-size:13px; }\nth,td { border:1px solid var(--border); padding:10px; vertical-align:top; }\nth { background:#eef2f7; text-align:left; color:#344054; }\n.bar { height:12px; background:#e4e7ec; border-radius:999px; overflow:hidden; }\n.bar > div { height:100%; background:var(--brand); border-radius:999px; }\n.reportbox { width:100%; min-height:520px; white-space:pre-wrap; background:#f8fafc; border:1px solid var(--border); border-radius:14px; padding:16px; font-family:Consolas, monospace; font-size:12px; line-height:1.5; }
.finding-card { border:1px solid var(--border); border-radius:18px; padding:18px; margin-bottom:18px; background:#fff; }
.finding-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; border-bottom:1px solid #e4e7ec; padding-bottom:12px; margin-bottom:12px; }
.claim-box { background:#f8fafc; border-left:4px solid var(--brand); padding:12px; border-radius:10px; margin:10px 0; }
.analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.analysis-block { background:#f8fafc; border:1px solid #e4e7ec; border-radius:14px; padding:14px; }\n.tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }\n.tab { background:#eef2f7; color:#344054; }\n.tab.active { background:var(--brand); color:white; }\n.hidden { display:none; }\n.error { color:var(--red); font-weight:800; }\n.success { color:var(--green); font-weight:800; }\n.report-container { background:white; color:#172033; }\n.report-header { border-bottom:4px solid var(--brand); padding-bottom:16px; margin-bottom:20px; }\n.report-title { font-size:28px; margin:0; color:var(--brand); }\n.report-subtitle { margin:5px 0 0; color:var(--muted); }\n.report-section { margin:24px 0; page-break-inside:avoid; }\n.report-table th { background:#eef2f7; }\n@media (max-width:950px) { .grid,.grid3,.grid4,.header-inner { grid-template-columns:1fr; display:block; } .grid > *, .grid3 > *, .grid4 > * { margin-bottom:14px; } }\n@media print {\n  header, .noprint, #inputSection, #actionsRow, #statusCard { display:none !important; }\n  body { background:white; }\n  main { max-width:none; padding:0; }\n  .card { border:none; box-shadow:none; padding:0; }\n  .onlyprint { display:block !important; }\n}\n.onlyprint { display:none; }\n</style>\n</head>\n<body>\n<header>\n  <div class="header-inner">\n    <div>\n      <h1>Social Washing Scan</h1>\n      <p style="margin-bottom:0;opacity:.92;">Prototype tool for social, labour, human rights, diversity and value-chain claim risk assessment.</p>\n    </div>\n    <div class="small" style="text-align:right;opacity:.9;">Hostable v5<br/>Prepared for external feedback testing</div>\n  </div>\n</header>\n\n<main>\n  <div class="card status noprint" id="statusCard"><strong>Status:</strong> <span id="status">Ready. Use text scan or URL scan.</span></div>\n\n  <section class="grid noprint" id="inputSection">\n    <div class="card">\n      <h2>1. Scan input</h2>\n      <label>Website URL</label>\n      <input id="urlInput" value="https://www.kbc.com" placeholder="https://www.company.com/sustainability"/>\n      <button onclick="scanUrl()">Scan URL</button>\n      <p class="muted small">The hosted server fetches one public webpage and analyses visible text. Some websites may block automated requests.</p>\n\n      <label>Text input</label>\n      <textarea id="textInput">At Company X, we put people first. We are fully committed to fair work, diversity, equality and human rights across our entire value chain. Our suppliers respect the highest labour standards and we ensure safe and inclusive working conditions for everyone.</textarea>\n      <button onclick="scanText()">Run text scan</button>\n      <button class="secondary" onclick="loadSample()">Use sample</button>\n    </div>\n\n    <div class="card">\n      <h2>2. Options and actions</h2>\n      <label><input type="checkbox" id="useAi" style="width:auto;"/> Use AI analysis if configured</label>\n      <p class="muted small">If no API key is configured on the server, the tool uses the built-in rule-based engine.</p>\n      <button class="secondary" onclick="checkBackend()">Check backend</button>\n      <hr style="border:0;border-top:1px solid var(--border);margin:18px 0;"/>\n      <h3>Export report</h3>\n      <button onclick="downloadProfessionalHtml()">Download professional HTML report</button>\n      <button class="secondary" onclick="printReport()">Print / Save as PDF</button>\n      <button class="secondary" onclick="selectReport()">Select text report</button>\n      <button class="secondary" onclick="copyReport()">Copy text report</button>\n      <p class="muted small">For feedback testing, use the public hosted URL and ask testers to try both text and URL scans.</p>\n    </div>\n  </section>\n\n  <section class="grid">\n    <div class="card">\n      <h2>Risk overview</h2>\n      <div class="score" id="score">--</div>\n      <div id="riskBadge" class="badge">Not scanned</div>\n      <p id="sourceLabel" class="muted"></p>\n      <p id="engine" class="muted"></p>\n      <div class="grid3">\n        <div class="kpi"><strong id="claimCount">0</strong><br/><span class="muted small">Findings</span></div>\n        <div class="kpi"><strong id="highCount">0</strong><br/><span class="muted small">High/very high</span></div>\n        <div class="kpi"><strong id="immediateCount">0</strong><br/><span class="muted small">Immediate</span></div>\n      </div>\n    </div>\n\n    <div class="card">\n      <h2>Executive summary</h2>\n      <p id="mainConclusion" class="muted">No scan completed yet.</p>\n      <div class="kpi">\n        <strong>Disclaimer</strong>\n        <p class="small muted" style="margin-bottom:0;">Indicative assessment only. Not legal advice and not a replacement for human rights due diligence, assurance or legal review.</p>\n      </div>\n    </div>\n  </section>\n\n  <section class="card" id="breakdownCard" style="display:none;">\n    <h2>Score breakdown</h2>\n    <div id="breakdown"></div>\n  </section>\n\n  <section class="card">\n    <h2>Claim-level findings</h2>\n    <div id="findings">No findings yet.</div>\n  </section>\n\n  <section class="card">\n    <h2>Governance recommendations</h2>\n    <div id="governance">No governance actions yet.</div>\n  </section>\n\n  <section class="card noprint">\n    <h2>Text report preview</h2>\n    <textarea id="reportPreview" class="reportbox" readonly>No report yet.</textarea>\n  </section>\n\n  <section id="printableReport" class="card report-container onlyprint"></section>\n</main>\n\n<script>\nlet lastResult = null;\n\nfunction setStatus(msg, isError=false){\n  document.getElementById("status").innerHTML = isError ? "<span class=\'error\'>" + esc(msg) + "</span>" : msg;\n}\nfunction esc(v){ return String(v || "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll(\'"\',"&quot;").replaceAll("\'","&#039;"); }\nfunction riskClass(r){ r=String(r||"").toLowerCase(); if(r.includes("very"))return"veryhigh"; if(r.includes("high"))return"high"; if(r.includes("medium"))return"medium"; return"low"; }\nfunction badge(r){ return `<span class="badge ${riskClass(r)}">${esc(r)}</span>`; }\nfunction useAi(){ return document.getElementById("useAi").checked; }\n\nasync function checkBackend(){\n  try{\n    setStatus("Checking backend...");\n    const res = await fetch("/api/health");\n    const data = await res.json();\n    if(!res.ok) throw new Error(JSON.stringify(data));\n    setStatus("Backend OK. Version: " + data.version + ". AI configured: " + data.ai_configured + ".");\n  } catch(e){\n    setStatus("Backend not reachable. If local, start app.py. If hosted, check deployment logs.", true);\n  }\n}\n\nasync function scanText(){\n  try{\n    const text = document.getElementById("textInput").value;\n    if(!text.trim()){ setStatus("Please paste text before scanning.", true); return; }\n    setStatus("Scanning text...");\n    const res = await fetch("/api/scan/text", {\n      method:"POST", headers:{"Content-Type":"application/json"},\n      body:JSON.stringify({text:text, source_label:"Manual text input", use_ai:useAi()})\n    });\n    const data = await res.json();\n    if(!res.ok || data.error) throw new Error(data.error || res.statusText);\n    render(data);\n    setStatus(data.ai_error ? "Scan completed with fallback engine. AI error: " + data.ai_error : "Text scan completed.");\n  } catch(e){ setStatus("Error: " + e.message, true); }\n}\n\nasync function scanUrl(){\n  try{\n    const url = document.getElementById("urlInput").value;\n    if(!url.trim()){ setStatus("Please enter a URL.", true); return; }\n    setStatus("Fetching live URL and analysing page text. This can take 10-20 seconds...");\n    const res = await fetch("/api/scan/url", {\n      method:"POST", headers:{"Content-Type":"application/json"},\n      body:JSON.stringify({url:url, use_ai:useAi()})\n    });\n    const data = await res.json();\n    if(!res.ok || data.error) throw new Error(data.error || res.statusText);\n    render(data);\n    setStatus(data.ai_error ? "URL scan completed with fallback engine. AI error: " + data.ai_error : "URL scan completed.");\n  } catch(e){\n    setStatus("Error: " + e.message + ". Some websites block automated scans. Copy page text and use text scan if this happens.", true);\n  }\n}\n\nfunction render(result){\n  lastResult = result;\n  document.getElementById("score").textContent = result.overall_score + "/100";\n  const rb = document.getElementById("riskBadge");\n  rb.textContent = result.overall_risk;\n  rb.className = "badge " + riskClass(result.overall_risk);\n  document.getElementById("sourceLabel").textContent = "Source: " + result.source_label;\n  document.getElementById("engine").textContent = "Engine: " + result.engine + " | Date: " + (result.analysis_date || "");\n  document.getElementById("mainConclusion").textContent = result.summary?.main_conclusion || "Scan completed.";\n\n  const findings = result.findings || [];\n  document.getElementById("claimCount").textContent = findings.length;\n  document.getElementById("highCount").textContent = findings.filter(f => ["High","Very high"].includes(f.risk)).length;\n  document.getElementById("immediateCount").textContent = findings.filter(f => f.priority === "Immediate").length;\n\n  renderBreakdown(result.score_breakdown || []);\n  renderFindings(findings);\n  renderGovernance(result.governance_actions || []);\n  document.getElementById("reportPreview").value = buildTextReport(result);\n  document.getElementById("printableReport").innerHTML = buildProfessionalReportHtml(result, false);\n}\n\nfunction renderBreakdown(rows){\n  const card = document.getElementById("breakdownCard");\n  if(!rows.length){ card.style.display = "none"; return; }\n  card.style.display = "block";\n  document.getElementById("breakdown").innerHTML = rows.map(r => `\n    <div style="margin-bottom:15px;">\n      <div style="display:flex;justify-content:space-between;gap:12px;"><strong>${esc(r.label)}</strong><span class="muted">${r.value}/100 · weight ${r.weight}% · weighted ${r.weighted}</span></div>\n      <div class="bar"><div style="width:${Number(r.value || 0)}%"></div></div>\n      <p class="muted small">${esc(r.explanation || "")}</p>\n    </div>\n  `).join("");\n}\n\nfunction renderFindings(findings){\n  if(!findings.length){ document.getElementById("findings").innerHTML = "No findings."; return; }\n  const rows = findings.map((f,i)=>`\n    <tr>\n      <td>${i+1}</td>\n      <td>${esc(f.detected_text)}</td>\n      <td>${esc(f.category)}</td>\n      <td>${badge(f.risk)}</td>\n      <td>${esc(f.priority)}</td>\n      <td>${esc(f.main_issue)}</td>\n      <td>${esc(f.evidence_required)}</td>\n      <td>${esc(f.recommended_action)}</td>\n      <td>${esc(f.suggested_rewrite)}</td>\n    </tr>\n  `).join("");\n  document.getElementById("findings").innerHTML = `<div style="overflow:auto;"><table><thead><tr><th>#</th><th>Detected text</th><th>Category</th><th>Risk</th><th>Priority</th><th>Main issue</th><th>Evidence required</th><th>Action</th><th>Suggested rewrite</th></tr></thead><tbody>${rows}</tbody></table></div>`;\n}\n\nfunction renderGovernance(actions){\n  document.getElementById("governance").innerHTML = "<ul>" + actions.map(a => "<li>" + esc(a) + "</li>").join("") + "</ul>";\n}\n\nfunction buildTextReport(result){\n  const lines = [];\n  lines.push("SOCIAL WASHING SCAN REPORT");\n  lines.push("================================");\n  lines.push("Source: " + result.source_label);\n  lines.push("Engine: " + result.engine);\n  lines.push("Analysis date: " + (result.analysis_date || ""));\n  lines.push("Overall score: " + result.overall_score + "/100");\n  lines.push("Overall risk: " + result.overall_risk);\n  lines.push("");\n  lines.push("1. EXECUTIVE SUMMARY");\n  lines.push(result.summary?.main_conclusion || "");\n  lines.push("");\n  if(result.score_breakdown && result.score_breakdown.length){\n    lines.push("2. SCORE BREAKDOWN");\n    result.score_breakdown.forEach(b => lines.push("- " + b.label + ": " + b.value + "/100, weight " + b.weight + "%, weighted contribution " + b.weighted + ". " + (b.explanation || "")));\n    lines.push("");\n  }\n  lines.push("CLAIM-LEVEL FINDINGS");\n  (result.findings || []).forEach((f,i)=>{\n    lines.push("");\n    lines.push((i+1) + ". " + f.category + " | Risk: " + f.risk + " | Priority: " + f.priority);\n    lines.push(\'Detected text: "\' + f.detected_text + \'"\');\n    lines.push("Main issue: " + f.main_issue);\n    lines.push("Legal sensitivity: " + f.legal_sensitivity);\n    lines.push("Stakeholders: " + f.stakeholders);\n    lines.push("Evidence required: " + f.evidence_required);\n    lines.push("Recommended action: " + f.recommended_action);\n    lines.push(\'Suggested rewrite: "\' + f.suggested_rewrite + \'"\');\n  });\n  lines.push("");\n  lines.push("4. GOVERNANCE RECOMMENDATIONS");\n  (result.governance_actions || []).forEach(a => lines.push("- " + a));\n  lines.push("");\n  lines.push("5. ANALYSED TEXT EXCERPT");\n  lines.push(result.analysed_text_excerpt || "");\n  lines.push("");\n  lines.push("DISCLAIMER");\n  lines.push(result.disclaimer || "Indicative assessment only.");\n  return lines.join("\\n");\n}\n\nfunction buildProfessionalReportHtml(result, fullDoc=true){\n  const findings = result.findings || [];\n  const breakdownRows = (result.score_breakdown || []).map(b => `\n    <tr><td>${esc(b.label)}</td><td>${b.weight}%</td><td>${b.value}/100</td><td>${b.weighted}</td><td>${esc(b.explanation || "")}</td></tr>\n  `).join("");\n  const findingRows = findings.map((f,i)=>`\n    <tr>\n      <td>${i+1}</td><td>${esc(f.detected_text)}</td><td>${esc(f.category)}</td><td>${esc(f.risk)}</td><td>${esc(f.priority)}</td>\n      <td>${esc(f.main_issue)}</td><td>${esc(f.evidence_required)}</td><td>${esc(f.recommended_action)}</td><td>${esc(f.suggested_rewrite)}</td>\n    </tr>\n  `).join("");\n  const html = `\n    <div class="report-header">\n      <h1 class="report-title">Social Washing Scan Report</h1>\n      <p class="report-subtitle">Indicative review of social, labour, human rights, diversity and value-chain claims</p>\n    </div>\n    <div class="report-section">\n      <h2>1. Executive summary</h2>\n      <div class="grid3">\n        <div class="kpi"><strong>${result.overall_score}/100</strong><br/><span class="muted">Overall score</span></div>\n        <div class="kpi"><strong>${esc(result.overall_risk)}</strong><br/><span class="muted">Risk level</span></div>\n        <div class="kpi"><strong>${findings.length}</strong><br/><span class="muted">Findings</span></div>\n      </div>\n      <p>${esc(result.summary?.main_conclusion || "")}</p>\n      <p class="muted small"><strong>Source:</strong> ${esc(result.source_label)}<br/><strong>Engine:</strong> ${esc(result.engine)}<br/><strong>Date:</strong> ${esc(result.analysis_date || "")}</p>\n    </div>\n    <div class="report-section">\n      <h2>2. Score breakdown</h2>\n      <table class="report-table"><thead><tr><th>Criterion</th><th>Weight</th><th>Risk score</th><th>Weighted contribution</th><th>Assessment focus</th></tr></thead><tbody>${breakdownRows}</tbody></table>\n    </div>\n    <div class="report-section">\n      <h2>3. Claim-level findings</h2>\n      <table class="report-table"><thead><tr><th>#</th><th>Detected text</th><th>Category</th><th>Risk</th><th>Priority</th><th>Main issue</th><th>Evidence required</th><th>Action</th><th>Suggested rewrite</th></tr></thead><tbody>${findingRows}</tbody></table>\n    </div>\n    <div class="report-section">\n      <h2>4. Governance recommendations</h2>\n      <ul>${(result.governance_actions || []).map(a => "<li>" + esc(a) + "</li>").join("")}</ul>\n    </div>\n    <div class="report-section">\n      <h2>5. Analysed text excerpt</h2>\n      <p class="small">${esc(result.analysed_text_excerpt || "")}</p>\n    </div>\n    <div class="report-section">\n      <h2>Disclaimer</h2>\n      <p class="small muted">${esc(result.disclaimer || "")}</p>\n    </div>`;\n  if(!fullDoc) return html;\n  return `<!doctype html><html><head><meta charset="utf-8"><title>Social Washing Scan Report</title><style>${document.querySelector("style").innerHTML}</style></head><body><main>${html}</main></body></html>`;\n}\n\nfunction downloadProfessionalHtml(){\n  if(!lastResult){ setStatus("No report yet. Run a scan first.", true); return; }\n  const html = buildProfessionalReportHtml(lastResult, true);\n  download("social-washing-scan-report.html", html, "text/html");\n}\n\nfunction printReport(){\n  if(!lastResult){ setStatus("No report yet. Run a scan first.", true); return; }\n  document.getElementById("printableReport").innerHTML = buildProfessionalReportHtml(lastResult, false);\n  window.print();\n}\n\nfunction selectReport(){\n  const box = document.getElementById("reportPreview");\n  box.focus(); box.select();\n  setStatus("Text report selected. Press Ctrl+C to copy.");\n}\n\nasync function copyReport(){\n  try{\n    await navigator.clipboard.writeText(document.getElementById("reportPreview").value);\n    setStatus("Text report copied to clipboard.");\n  } catch(e){ selectReport(); }\n}\n\nfunction download(filename, content, type){\n  const blob = new Blob([content], {type});\n  const url = URL.createObjectURL(blob);\n  const a = document.createElement("a");\n  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);\n  setStatus("Download triggered. If blocked, use Select text report or Print / Save as PDF.");\n}\n\nfunction loadSample(){\n  document.getElementById("textInput").value = "At Company X, we put people first. We are fully committed to fair work, diversity, equality and human rights across our entire value chain. Our suppliers respect the highest labour standards and we ensure safe and inclusive working conditions for everyone.";\n  setStatus("Sample loaded. Click Run text scan.");\n}\n\ncheckBackend();\n</script>\n</body>\n</html>\n'

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
        "User-Agent": "Mozilla/5.0 SocialWashingScanHostable/4.0",
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
        rows.append({
            **criterion,
            "value": value,
            "weighted": round(value * criterion["weight"] / 100)
        })
    return rows

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
            "main_issue": rule["issue"],
            "legal_sensitivity": rule["legal"],
            "stakeholders": rule["stakeholders"],
            "evidence_required": rule["evidence"],
            "recommended_action": rule["action"],
            "suggested_rewrite": rule["rewrite"],
            "scores": rule["scores"],
            "numerical_risk": numerical,
            "issue_type": rule.get("issue_type", rule["category"]),
            "detected_issue": rule.get("detected_issue", rule["issue"]),
            "risk_rationale": rule.get("risk_rationale", rule["legal"]),
            "assessment_text": (
                "The detected wording falls under '" + rule["category"] + "'. "
                + rule.get("detected_issue", rule["issue"]) + " "
                + rule.get("risk_rationale", rule["legal"]) + " "
                + "Recommended correction: " + rule["action"]
            )
        })

    if not findings:
        findings.append({
            "detected_text": text[:280] + ("..." if len(text) > 280 else ""),
            "category": "General social responsibility statement",
            "risk": "Low",
            "priority": "Monitor",
            "main_issue": "No obvious high-risk social washing wording was detected by the rule-based engine.",
            "legal_sensitivity": "Low based on current wording, but context and evidence should still be reviewed.",
            "stakeholders": "General stakeholders.",
            "evidence_required": "Policy documents, KPIs, governance responsibilities and reporting evidence.",
            "recommended_action": "Keep the claim specific, evidence-based and scoped.",
            "suggested_rewrite": "Use precise wording linked to measurable actions, reporting period and scope.",
            "scores": {"specificity": 20, "evidence": 25, "scope": 25, "assurance": 25, "sensitivity": 20, "misleading": 20},
            "numerical_risk": 23
        })

    findings = sorted(findings, key=lambda x: x["numerical_risk"], reverse=True)
    breakdown = score_breakdown(findings)
    overall_score = max(8, min(96, sum(row["weighted"] for row in breakdown)))
    if any(f["risk"] == "Very high" for f in findings):
        overall_score = max(overall_score, 76)

    immediate = sum(1 for f in findings if f["priority"] == "Immediate")
    high = sum(1 for f in findings if f["risk"] in ("High", "Very high"))

    return {
        "source_label": source_label,
        "engine": "structured_rule_based_v5",
        "analysis_date": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "overall_score": overall_score,
        "overall_risk": risk_from_score(overall_score),
        "score_breakdown": breakdown,
        "summary": {
            "finding_count": len(findings),
            "high_or_very_high_count": high,
            "immediate_priority_count": immediate,
            "main_conclusion": conclusion_text(overall_score, findings)
        },
        "findings": findings,
        "governance_actions": [
            "Create and maintain a register of social, labour, human rights, diversity and supplier claims.",
            "Assign claim ownership to sustainability, HR, procurement, legal and communications teams.",
            "Require evidence before publication, including scope, data source, methodology and date.",
            "Escalate high-risk claims about suppliers, human rights and diversity to legal/compliance review.",
            "Review claims periodically to ensure they remain accurate and substantiated.",
            "For high-risk supplier or human rights claims, require due diligence documentation before publication."
        ],
        "disclaimer": "Indicative assessment only. Not legal advice and not a replacement for human rights due diligence, assurance or legal review.",
        "analysed_text_excerpt": text[:2500]
    }

def conclusion_text(score, findings):
    if score >= 76:
        return "The analysed content contains high-sensitivity social washing risk signals. Claims should be reviewed before publication and supported by clear evidence, scope and governance controls."
    if score >= 56:
        return "The analysed content contains several social washing risk signals. The priority is to qualify broad claims, clarify scope and strengthen the evidence trail."
    if score >= 31:
        return "The analysed content contains moderate social washing risk signals. Targeted improvements to wording, scope and substantiation are recommended."
    return "The analysed content shows limited social washing risk signals based on the current rule-based review, but evidence and context should still be checked."

def read_api_key():
    return os.environ.get("OPENAI_API_KEY", "").strip()

def extract_json_from_text(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end+1]
    return text

def ai_analyse(text, source_label):
    api_key = read_api_key()
    if not api_key:
        return None

    prompt = f"""
You are an ESG and social washing risk assessment engine.
Analyse the text for potentially misleading or insufficiently substantiated social, labour, human rights, diversity, inclusion, health and safety, supplier and value-chain claims.

Return ONLY valid JSON with this exact structure:
{{
  "source_label": "{source_label}",
  "engine": "openai_ai_analysis",
  "analysis_date": string,
  "overall_score": integer 0-100,
  "overall_risk": "Low" | "Medium" | "High" | "Very high",
  "score_breakdown": [
    {{"key": "specificity", "label": "Claim specificity", "weight": 15, "value": integer, "weighted": integer, "explanation": string}},
    {{"key": "evidence", "label": "Evidence quality", "weight": 25, "value": integer, "weighted": integer, "explanation": string}},
    {{"key": "scope", "label": "Scope clarity", "weight": 15, "value": integer, "weighted": integer, "explanation": string}},
    {{"key": "assurance", "label": "Verification / assurance", "weight": 15, "value": integer, "weighted": integer, "explanation": string}},
    {{"key": "sensitivity", "label": "Stakeholder sensitivity", "weight": 15, "value": integer, "weighted": integer, "explanation": string}},
    {{"key": "misleading", "label": "Misleading impression risk", "weight": 15, "value": integer, "weighted": integer, "explanation": string}}
  ],
  "summary": {{
    "finding_count": integer,
    "high_or_very_high_count": integer,
    "immediate_priority_count": integer,
    "main_conclusion": string
  }},
  "findings": [
    {{
      "detected_text": string,
      "category": string,
      "risk": "Low" | "Medium" | "High" | "Very high",
      "priority": "Monitor" | "Medium term" | "Short term" | "Immediate",
      "main_issue": string,
      "legal_sensitivity": string,
      "stakeholders": string,
      "evidence_required": string,
      "recommended_action": string,
      "suggested_rewrite": string,
      "scores": {{"specificity": integer, "evidence": integer, "scope": integer, "assurance": integer, "sensitivity": integer, "misleading": integer}},
      "numerical_risk": integer
    }}
  ],
  "governance_actions": [string],
  "disclaimer": string
}}

Text to analyse:
{text[:45000]}
"""
    payload = {"model": OPENAI_MODEL, "input": prompt}
    req = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        output_text = data.get("output_text", "")
        if not output_text:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") in ("output_text", "text"):
                        output_text += content.get("text", "")
        parsed = json.loads(extract_json_from_text(output_text))
        parsed["source_label"] = source_label
        parsed["engine"] = "openai_ai_analysis"
        parsed["analysed_text_excerpt"] = text[:2500]
        return parsed
    except Exception as exc:
        fallback = rule_based_analyse(text, source_label)
        fallback["engine"] = "structured_rule_based_v5_ai_failed"
        fallback["ai_error"] = str(exc)
        return fallback

def analyse(text, source_label, use_ai):
    if use_ai:
        ai_result = ai_analyse(text, source_label)
        if ai_result:
            return ai_result
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
            self._send(FRONTEND_HTML)
        elif self.path == "/api/health":
            self._send_json({
                "status": "ok",
                "version": "hostable_v5",
                "ai_configured": bool(read_api_key())
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw or "{}")
            use_ai = bool(data.get("use_ai", False))

            if self.path == "/api/scan/text":
                text = data.get("text", "")
                if not text.strip():
                    self._send_json({"error": "No text provided"}, 400)
                    return
                self._send_json(analyse(text[:MAX_TEXT_CHARS], data.get("source_label", "Manual text input"), use_ai))
                return

            if self.path == "/api/scan/url":
                url = data.get("url", "")
                if not url:
                    self._send_json({"error": "No URL provided"}, 400)
                    return
                text = fetch_url_text(url)
                self._send_json(analyse(text, url, use_ai))
                return

            self._send_json({"error": "Unknown endpoint"}, 404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

def main():
    print("Social Washing Scan Hostable v5")
    print(f"Serving on http://{HOST}:{PORT}")
    print("AI configured:", "yes" if read_api_key() else "no")
    HTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
