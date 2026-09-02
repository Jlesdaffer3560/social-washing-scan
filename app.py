#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin, quote, parse_qs
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener, install_opener
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from html import escape as html_escape
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime, base64, zipfile, re, io, time, gzip, zlib, hmac, hashlib, secrets, threading, unicodedata, csv
from concurrent.futures import ThreadPoolExecutor, as_completed

def _get_build_company_report_pdf():
    """Lazily import the ReportLab-based PDF generator on first use, instead of at
    module load time. This guarantees the HTTP server can bind its port and start
    immediately even if the reportlab import is slow, memory-heavy or fails on a
    given host -- only the PDF-download endpoint is affected, not server startup."""
    global _report_pdf_fn, _report_pdf_import_error
    if _report_pdf_fn is not None:
        return _report_pdf_fn
    if _report_pdf_import_error is not None:
        return None
    try:
        from report_pdf import build_company_report_pdf as _fn
        _report_pdf_fn = _fn
        return _fn
    except Exception as e:
        _report_pdf_import_error = str(e)
        return None
_report_pdf_fn = None
_report_pdf_import_error = None

def _get_pypdf():
    """Lazily import pypdf on first use, same pattern as the ReportLab lazy import above:
    server startup must never be blocked or crashed by a PDF library import issue -- only
    PDF *reading* is affected if the import fails, not the rest of the app."""
    global _pypdf_module, _pypdf_import_error
    if _pypdf_module is not None:
        return _pypdf_module
    if _pypdf_import_error is not None:
        return None
    try:
        import pypdf as _p
        _pypdf_module = _p
        return _p
    except Exception as e:
        _pypdf_import_error = str(e)
        return None
_pypdf_module = None
_pypdf_import_error = None

def _get_psycopg():
    """Lazily import psycopg on first use, same pattern as the PDF-library lazy imports
    above: the scan-history feature is entirely optional (gated on DATABASE_URL being
    configured), so a missing/broken psycopg install must never block server startup or
    the rest of the app -- only history saving/viewing is affected.
    v92.2: uses psycopg (v3), not psycopg2 -- psycopg2-binary==2.9.9 failed to import at
    all on this deployment ("undefined symbol: _PyInterpreterState_Get") because Render
    is actually running Python 3.14 despite render.yaml pinning PYTHON_VERSION to 3.12.7
    (env vars set directly in the dashboard, from an earlier point, take precedence over a
    blueprint sync -- the same behaviour already seen with the EXTERNAL_SIGNAL_* vars).
    psycopg2 is legacy/maintenance-only and lags new CPython internals; psycopg (v3) is
    actively maintained with current-Python wheels, and its basic connect/cursor/execute
    API used here is essentially identical, so this sidesteps the Python-version mismatch
    entirely rather than depending on getting that pin to actually take effect."""
    global _psycopg_module, _psycopg_import_error
    if _psycopg_module is not None:
        return _psycopg_module
    if _psycopg_import_error is not None:
        return None
    try:
        import psycopg as _pg
        _psycopg_module = _pg
        return _pg
    except Exception as e:
        _psycopg_import_error = str(e)
        return None
_psycopg_module = None
_psycopg_import_error = None

APP_VERSION="hostable_v92_6_view_selected_filter"
APP_RELEASE_LABEL="v92.6"
APP_RELEASE_DATE="2026-09-01"
MAX_REQUEST_BYTES=max(1_000_000, min(25_000_000, int(os.environ.get("MAX_REQUEST_BYTES", "12000000"))))
RATE_LIMIT_WINDOW_SECONDS=max(60, int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "3600")))
RATE_LIMIT_SCANS=max(1, int(os.environ.get("RATE_LIMIT_SCANS", "5")))
RATE_LIMIT_REPORTS=max(1, int(os.environ.get("RATE_LIMIT_REPORTS", "20")))
MAX_CONCURRENT_SCANS=max(1, min(4, int(os.environ.get("MAX_CONCURRENT_SCANS", "2"))))
ALLOWED_ORIGINS={x.strip().rstrip('/') for x in os.environ.get("DURABLY_ALLOWED_ORIGINS", "").split(',') if x.strip()}
_REPORT_SIGNING_KEY_TEXT=os.environ.get("DURABLY_REPORT_SIGNING_KEY", "").strip()
_REPORT_SIGNING_KEY_CONFIGURED=bool(_REPORT_SIGNING_KEY_TEXT)
# v73: the previous fallback derived the key deterministically from a public string plus
# APP_VERSION -- both visible in this open source file and even echoed back by /api/health's
# "version" field, so anyone with the source could compute it and forge valid report tokens
# for arbitrary report/email requests. A random per-process key closes that hole: it cannot be
# derived from the source, and signing/verification still works correctly for the lifetime of
# one running process (the only cost is that in-flight tokens are invalidated by a restart,
# same as before for the deterministic fallback's underlying tradeoff). Configuring
# DURABLY_REPORT_SIGNING_KEY in production is still strongly recommended so tokens survive a
# Render worker restart.
_REPORT_SIGNING_KEY=(_REPORT_SIGNING_KEY_TEXT.encode("utf-8") if _REPORT_SIGNING_KEY_CONFIGURED
                     else secrets.token_bytes(32))
REPORT_TOKEN_MAX_AGE_SECONDS=max(900,min(86400,int(os.environ.get("REPORT_TOKEN_MAX_AGE_SECONDS","21600"))))
_RATE_LOCK=threading.Lock()
_RATE_EVENTS={}
_SCAN_SEMAPHORE=threading.BoundedSemaphore(MAX_CONCURRENT_SCANS)
# v56: standard browser User-Agent instead of a self-identifying scanner UA. A UA string
# that announces itself as an assessment/scanner tool is the easiest possible fingerprint
# for corporate bot-protection (Akamai/PerimeterX/Cloudflare-style WAFs) to block on,
# independent of any other fingerprinting. This does not defeat sophisticated bot
# detection, but removes the most trivial and unnecessary self-inflicted cause of it.
CRAWLER_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
# v59: crawl more than the first three candidate pages. The crawler keeps trying
# additional discovered URLs until it has enough usable pages or reaches the shared
# time/attempt budget. These values can be tuned in Render without changing code.
CRAWL_TARGET_EXTRA_PAGES=max(3, min(10, int(os.environ.get("CRAWL_TARGET_EXTRA_PAGES", "8"))))
CRAWL_MAX_PAGE_ATTEMPTS=max(CRAWL_TARGET_EXTRA_PAGES, min(24, int(os.environ.get("CRAWL_MAX_PAGE_ATTEMPTS", "14"))))
CRAWL_BUDGET_SECONDS=max(16, min(35, int(os.environ.get("CRAWL_BUDGET_SECONDS", "24"))))
CRAWL_FETCH_WORKERS=max(2, min(5, int(os.environ.get("CRAWL_FETCH_WORKERS", "4"))))
ENABLE_READER_FALLBACK=os.environ.get("ENABLE_READER_FALLBACK", "1").strip().lower() not in {"0","false","no","off"}
JINA_API_KEY=os.environ.get("JINA_API_KEY", "").strip()

BROWSER_USER_AGENTS=[
    CRAWLER_USER_AGENT,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]
# v56: known corporate-group domains that are not simple TLD variants of the scanned
# brand's own hostname (e.g. zara.com's real sustainability/CSR reporting lives mainly
# under the parent group's own domain, not under zara.<tld>). Extend this map as more
# gaps are found; it is deliberately conservative (kept in sync with PROFILES aliases).
KNOWN_GROUP_DOMAINS={
    "zara":["https://www.inditex.com"],
    "inditex":["https://www.zara.com"],
}
PORT=int(os.environ.get("PORT","8000"))
HOST="0.0.0.0"
APP_DIR=Path(__file__).resolve().parent
TAVILY_API_KEY=os.environ.get("TAVILY_API_KEY","").strip()
OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY","").strip()
GOOGLE_SEARCH_API_KEY=os.environ.get("GOOGLE_SEARCH_API_KEY","").strip()
GOOGLE_SEARCH_CX=os.environ.get("GOOGLE_SEARCH_CX","").strip()
SERPER_API_KEY=os.environ.get("SERPER_API_KEY","").strip()

def external_search_configured():
    """v73: single source of truth for whether external public-source search is available.
    Previously several checks tested only TAVILY_API_KEY / Google, so a deployment configured
    with only SERPER_API_KEY was incorrectly reported as having no external search available."""
    return bool(TAVILY_API_KEY or SERPER_API_KEY or (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX))
# Report-email delivery uses Brevo's HTTPS transactional-email API rather than raw SMTP:
# Render blocks outbound traffic on SMTP ports (25/465/587) for free web services, so an
# smtplib connection to any SMTP host fails there with "Network is unreachable" regardless
# of credentials. HTTPS (443) is not affected.
BREVO_API_KEY=os.environ.get("BREVO_API_KEY","").strip()
BREVO_SENDER_EMAIL=os.environ.get("BREVO_SENDER_EMAIL","").strip()
# v92: optional scan-history log, so the operator can see which companies were scanned and
# with what result -- useful once the tool is used by people other than the operator.
# DATABASE_URL is a standard Postgres connection string (e.g. from a free Neon/Supabase
# project); HISTORY_ADMIN_PASSWORD gates the /history page behind a single shared password
# (a full multi-user account system is not needed -- this is one operator's own private
# view, not a public feature). Both are optional: with either unset, /history and the
# history-save call both no-op gracefully rather than failing the scan itself.
DATABASE_URL=os.environ.get("DATABASE_URL","").strip()
HISTORY_ADMIN_PASSWORD=os.environ.get("HISTORY_ADMIN_PASSWORD","").strip()
_HISTORY_COOKIE_NAME='durably_history_auth'
_HISTORY_SESSION_SECONDS=30*24*3600

PROFILES={
 "kbc":("KBC","Banking and financial services","Medium","Responsible-finance, customer-protection, accessibility and financial-inclusion claims can be sensitive because financing decisions may create indirect social impacts."),
 "delhaize":("Delhaize","Food retail and supermarkets","High","Food retail can involve franchise labour, supplier pressure, agricultural labour, affordability claims and value-chain human-rights risks."),
 "aldi":("Aldi","Discount food retail","High","Discount food retail has exposure to purchasing practices, agricultural supply chains, migrant or seasonal labour and responsible-sourcing claims."),
 "lidl":("Lidl","Discount food retail","High","Discount food retail has exposure to purchasing practices, agricultural supply chains, migrant or seasonal labour and responsible-sourcing claims."),
 "zara":("Zara / Inditex","Fast fashion and apparel retail","High","Fast fashion supply chains are exposed to labour-rights, subcontracting, wages, audit quality, traceability and worker-voice risks."),
 "inditex":("Inditex / Zara","Fast fashion and apparel retail","High","Fast fashion supply chains are exposed to labour-rights, subcontracting, wages, audit quality, traceability and worker-voice risks."),
 "fluxys":("Fluxys","Gas infrastructure and energy transport","Medium","Energy infrastructure has exposure to safety, contractor management, local communities, emergency preparedness and responsible procurement."),
 "proximus":("Proximus","Telecommunications and digital services","Medium","Telecom social claims may concern digital inclusion, vulnerable customers, privacy, cybersecurity, supply-chain labour and responsible digitalisation.")
}
SECTOR_RULES=[
 # v86: "platform" was removed -- it is standard SaaS/tech terminology ("our software
 # platform...") and matched essentially any tech company, not just gig-economy delivery
 # platforms (which "delivery" already covers on its own).
 ("High",["fast fashion","apparel","textile","garment","fashion","clothing","discount","supermarket","grocery","food retail","catering","facilities","outsourced","delivery","commodity","cocoa","palm oil","coffee","cotton"],"higher exposure to low-wage work, complex supply chains, migrant or seasonal labour, supplier pressure, audit limitations and worker-voice challenges"),
 ("Medium",["bank","finance","insurance","telecom","digital","aviation","airline","transport","chemical","energy","infrastructure","manufacturing","industrial","technology","utility","gas","logistics"],"meaningful exposure to customer rights, contractor management, responsible procurement, safety, data/privacy or affected-community expectations"),
 ("Low",["software","consulting","professional services","agency","office services"],"lower structural exposure, although broad people, customer or supply-chain claims still require evidence")
]


SOCIAL_WASHING_TAXONOMY={
 "Broad social-impact claim":"Community or social-impact washing",
 "Broad ethical or responsible-business claim":"Responsible-business washing",
 "Human-rights or labour-rights claim":"Human-rights or labour-rights washing",
 "Forced-labour product or supply-chain claim":"Forced-labour / product-market compliance washing",
 "Supply-chain or supplier-responsibility claim":"Supplier responsibility washing",
 "Diversity, equality and inclusion claim":"Diversity or inclusion washing",
 "Health, safety or worker-welfare claim":"Worker welfare washing",
 "Customer welfare or accessibility claim":"Customer fairness or accessibility washing",
 "Absolute or broad wording":"Overstatement / absolute-claim risk",
 "No major high-risk social claim detected":"No clear social-washing signal"
}

STANDARDS=[
 {"name":"CSRD / ESRS S1-S4 (post-Omnibus I: >1,000 employees AND >EUR450M net turnover; reporting from FY2027)","use":"Connect social claims to policies, actions, targets and metrics across own workforce (S1), value-chain workers (S2), affected communities (S3) and consumers (S4). Post-Omnibus I: first CSRD report due 2028 for in-scope companies. Belgian CSRD transposition: Law of 2 December 2024 (published in the Belgian State Gazette on 20 December 2024). Post-Omnibus scope changes: Directive (EU) 2026/470."},
 {"name":"CSDDD (post-Omnibus I: scope limited to >5,000 employees AND >EUR1.5B net turnover; application from 26 July 2029)","use":"Support human-rights and supply-chain claims with risk-based due diligence, prevention, mitigation, tracking and remediation. Post-Omnibus I (Directive 2026/470, in force 18 March 2026): direct scope applies only to the largest companies. Indirect exposure through customer due diligence expectations is already commercially relevant."},
 {"name":"EU Forced Labour Regulation - Regulation (EU) 2024/3015 (core prohibition, investigation and customs-enforcement provisions apply from 14 December 2027; a small set of governance/preparatory articles -- Art. 5(3), 7, 8, 9(2), 11, 33, 35 and 37(3) -- already apply from 13 December 2024)","use":"A product-market-access and customs-enforcement regime, not a claims/advertising law like EmpCo: it prohibits placing, making available on the Union market, or exporting products made in whole or in part with forced labour (Art. 3), enforced via investigation, withdrawal, disposal and customs suspension (Art. 17-30) rather than by policing marketing text. Article 1(3) explicitly states it does not itself create new due-diligence obligations -- due diligence already required under other Union/national law, or carried out per OECD/ILO guidance, is what investigators rely on as evidence. For this scan's purposes: treat 'forced-labour free', traceability or import/export assurance wording as a claim that should be backed by risk-based due diligence, product/supplier traceability, remediation and withdrawal/customs response readiness now, ahead of the 2027 application date -- not as proof the Regulation's own market-prohibition duties are already enforceable today."},
 {"name":"OECD Guidelines","use":"Check whether responsible-business claims are backed by identification, prevention, mitigation and accounting for adverse impacts."},
 {"name":"UN Guiding Principles on Business and Human Rights","use":"Support human-rights claims with policy commitment, due diligence, grievance channels and remedy."},
 {"name":"UN Global Compact","use":"Check consistency with principles on human rights, labour, environment and anti-corruption when responsible-business conduct is invoked."},
 {"name":"ILO Fundamental Principles and Rights at Work","use":"Check worker and supplier claims against freedom of association, collective bargaining, forced labour, child labour, non-discrimination and safe work."},
 {"name":"GRI Standards","use":"Check whether claims are balanced, evidence-based and supported by impacts, management approach, indicators and corrective actions."}
]
def standards_for_claim(t):
    x=(t or "").lower()
    # v57c: Directive (EU) 2024/825 ("EmpCo") Article 6(1)(b), as amended, explicitly brings
    # "social characteristics" of a product/trader within the misleading-claims test alongside
    # environmental ones -- Recital 3 names wages, social protection, safety of the work
    # environment, social dialogue, human rights, equal treatment, gender equality, inclusion,
    # diversity and ethical commitments as examples. EmpCo is therefore also directly relevant
    # to these social-claim categories, not only to green claims as previously cited here.
    if "forced" in x or "modern slavery" in x: return ["EU Forced Labour Regulation 2024/3015","CSRD/ESRS S2","CSDDD","OECD Guidelines","UNGPs","ILO","UNGC"]
    # v86: Art. 6(2)(d) is textually an "environmental claim related to future environmental
    # performance" test -- it does not itself extend to future SOCIAL-performance claims the
    # way Art. 6(1)(b) explicitly does. Citing "& 6(2)(d)" alongside 6(1)(b) here, even
    # parenthetically qualified "by analogy", still read as if 6(2)(d) were a direct legal
    # basis for this social-claim category. Reframed as an internal evidentiary standard this
    # scan applies by analogy, not a citation of the article itself.
    if "aspirational" in x or "future social" in x: return ["EmpCo / Directive (EU) 2024/825 Art. 6(1)(b) (social characteristics) -- future-performance evidentiary standard inspired by Art. 6(2)(d)'s environmental-claim logic, not a direct Art. 6(2)(d) requirement for social claims: a verifiable, time-bound implementation plan is expected before an aspirational social claim is treated as substantiated","CSRD/ESRS S1-S2","OECD Guidelines","UNGPs","ILO","UNGC"]
    if "human" in x or "labour" in x or "labor" in x: return ["EmpCo / Directive (EU) 2024/825 Art. 6(1)(b) (social characteristics: human/labour rights)","CSRD/ESRS S1-S2","CSDDD","EU Forced Labour Regulation 2024/3015","OECD Guidelines","UNGPs","ILO","UNGC"]
    if "supply" in x or "supplier" in x: return ["CSRD/ESRS S2","CSDDD","OECD Guidelines","UNGPs","ILO"]
    if "diversity" in x or "inclusion" in x: return ["EmpCo / Directive (EU) 2024/825 Art. 6(1)(b) (social characteristics: equal treatment, gender equality, inclusion, diversity)","CSRD/ESRS S1","ILO","GRI","UNGC"]
    if "customer" in x or "accessibility" in x: return ["CSRD/ESRS S4","OECD Guidelines","GRI"]
    if "worker" in x or "safety" in x: return ["EmpCo / Directive (EU) 2024/825 Art. 6(1)(b) (social characteristics: safety of the work environment)","CSRD/ESRS S1","ILO","GRI"]
    if "impact" in x or "community" in x: return ["CSRD/ESRS S3","UNGPs","OECD Guidelines","GRI"]
    return ["CSRD/ESRS S1-S4","OECD Guidelines","UNGC","GRI"]
def clean_excerpt(text,trig):
    if not trig: return text[:360]+("..." if len(text)>360 else "")
    low=text.lower(); i=low.find(trig.lower())
    if i<0: return text[:360]+("..." if len(text)>360 else "")
    starts=[text.rfind(".",0,i), text.rfind("\n",0,i)]
    s=max(starts)
    s=0 if s<0 else s+1
    ends=[p for p in [text.find(".",i+len(trig)), text.find("\n",i+len(trig))] if p!=-1]
    e=(min(ends)+1) if ends else min(len(text), i+len(trig)+260)
    out=" ".join(text[s:e].split())
    if len(out)<45: out=" ".join(text[max(0,i-130):min(len(text),i+len(trig)+240)].split())
    return out[:560]+("..." if len(out)>560 else "")
def _source_status(text):
    """v57q: classify a retained external signal by how far it has progressed, not just whether
    negative keywords are present -- an unproven allegation and a final court ruling carry very
    different weight and should not be presented identically."""
    t=text.lower()
    if any(x in t for x in ['ruled','ruling','fined','sentenced','convicted','found guilty','ordered to pay','court found','tribunal found','settlement reached','verdict']):
        return 'Decision / ruling'
    if any(x in t for x in ['investigation','investigating','probe','inquiry','under review by regulator','opened a case']):
        return 'Investigation / regulatory review'
    if any(x in t for x in ['lawsuit','filed a complaint','files complaint','sues','sued','legal action','court case']):
        return 'Legal complaint filed'
    if any(x in t for x in ['accused','alleg','claims that','reportedly']):
        return 'Allegation (unproven)'
    return 'Unclear status'

def _source_severity(text):
    t=text.lower()
    severe=['forced labour','forced labor','child labour','child labor','modern slavery','human rights abuse','fined','penalty','sanction','court','ruling','conviction','ban','prohibited']
    if any(x in t for x in severe): return 'High'
    return 'Medium'

def _dedupe_similar_sources(items):
    """v57q: cluster near-duplicate articles about the same underlying incident (common when
    several outlets cover one story) into a single retained entry with a count, instead of
    listing the same event repeatedly as if it were several independent signals."""
    def _sig(it):
        title=(it.get('title','') or '').lower()
        words=[w for w in re.findall(r'[a-zà-öø-ÿ]{4,}', title) if w not in ('this','that','with','from','have','been','will','their','about')]
        return frozenset(words[:8])
    clusters=[]
    for it in items:
        sig=_sig(it)
        matched=False
        for c in clusters:
            overlap=len(sig & c['sig'])
            if sig and c['sig'] and overlap/max(1,min(len(sig),len(c['sig']))) >= 0.6:
                c['items'].append(it); matched=True; break
        if not matched:
            clusters.append({'sig':sig,'items':[it]})
    out=[]
    for c in clusters:
        primary=c['items'][0]
        if len(c['items'])>1:
            primary=dict(primary)
            primary['related_articles_count']=len(c['items'])
        out.append(primary)
    return out


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip_depth=0; self.parts=[]; self.links=[]; self.skip_tags={"script","style","noscript","svg","canvas","form"}
    def handle_starttag(self,tag,attrs):
        tag_l=tag.lower()
        # v86: a single boolean flipped to False the moment ANY skip-tag closed, even a nested
        # one -- "<form><svg>...</svg>text after svg but still inside form</form>" incorrectly
        # let "text after svg" back into the scanned text once </svg> closed, despite the <form>
        # still being open. A depth counter (incremented per open, decremented per close, floored
        # at 0 for malformed/mismatched HTML) tracks nesting correctly.
        if tag_l in self.skip_tags: self.skip_depth+=1
        # Capture visible/semantic cues from images, icons and ARIA labels. These are not treated as proof,
        # but they help detect visual green-claim indicators such as leaf badges, eco icons or trust marks.
        attr_map={k.lower():v for k,v in attrs if v}
        if tag_l in {"img","svg","use","span","div","i"}:
            cues=[]
            for key in ["alt","title","aria-label","class","id","src"]:
                val=attr_map.get(key,"")
                if val and any(t in val.lower() for t in ["green","eco","leaf","tree","planet","earth","recycl","sustain","carbon","climate","water-drop","waterdrop","badge","label"]):
                    cues.append(val)
            if cues:
                self.parts.append("VISUAL CLAIM CUE: "+" | ".join(cues)[:240])
        if tag_l=="a":
            for k,v in attrs:
                if k.lower()=="href" and v: self.links.append(v)
    def handle_endtag(self,tag):
        if tag.lower() in self.skip_tags and self.skip_depth>0: self.skip_depth-=1
    def handle_data(self,data):
        if not self.skip_depth:
            t=" ".join(data.split())
            if len(t)>2: self.parts.append(t)

def parse_html(html):
    p=Parser(); p.feed(html); seen=set(); out=[]
    for t in p.parts:
        l=t.lower()
        if l not in seen: out.append(t); seen.add(l)
    return "\n".join(out), p.links
def norm_url(u):
    u=u.strip()
    if not u: raise ValueError("Please enter a company website URL.")
    return u if u.startswith(("http://","https://")) else "https://"+u

def looks_like_domain_or_url(raw):
    """True when the input already looks like a usable domain or URL
    (has a scheme, or a dot-separated host such as inditex.com / www.inditex.be)."""
    raw=(raw or '').strip()
    if not raw: return False
    if raw.startswith(("http://","https://")): return True
    if " " in raw: return False
    return bool(re.match(r'^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9-]{1,63})+(?:/.*)?$', raw))

NON_OFFICIAL_SITE_DOMAINS = {
    'wikipedia.org','wikidata.org','linkedin.com','facebook.com','twitter.com','x.com','instagram.com',
    'youtube.com','tiktok.com','bloomberg.com','crunchbase.com','glassdoor.com','indeed.com','reuters.com',
    'forbes.com','wsj.com','ft.com','nytimes.com','yahoo.com','google.com','duckduckgo.com','bing.com',
    'trustpilot.com','pitchbook.com','owler.com','zoominfo.com','apple.com','play.google.com','amazon.com',
    'ecosia.org','yelp.com','github.com','medium.com','pinterest.com'
}

def slugify_company_name(name):
    s=re.sub(r'[^a-z0-9]+','',(name or '').lower())
    return s or 'company'

def resolve_scan_input(raw):
    """Accepts a bare company name, a bare domain, or a full URL/page and returns
    (url, resolution_note). resolution_note is None when the input was already a
    usable domain or URL and needed no resolution."""
    raw=(raw or '').strip()
    if not raw: raise ValueError("Please enter a company name or website.")
    if looks_like_domain_or_url(raw):
        return norm_url(raw), None
    return resolve_company_website(raw)

def related_company_sites(url, max_sites=1):
    """Return a small set of likely related corporate/national domains.
    Example: www.lidl.be -> www.lidl.com. This is a cautious heuristic: it does not
    crawl the open web, it only tests common corporate TLD variants for the same brand.
    """
    parsed=urlparse(url)
    host=(parsed.hostname or '').lower()
    if not host: return []
    parts=host.split('.')
    if len(parts)<2: return []
    # Strip www and use the brand/core domain. Handles simple cases like www.lidl.be.
    core_parts=[x for x in parts if x not in {'www','m'}]
    if len(core_parts)<2: return []
    brand=core_parts[-2]
    if not brand or len(brand)<3: return []
    candidates=[]
    for tld in ['com','eu','be','nl','fr','de']:
        cand=f"https://www.{brand}.{tld}"
        if cand.rstrip('/') != url.rstrip('/') and (urlparse(cand).hostname or '') != host:
            candidates.append(cand)
    seen=[]
    for c in candidates:
        if c not in seen: seen.append(c)
    return seen[:max_sites]

def related_group_sites(url, max_sites=2):
    """v56: extends related_company_sites (same-brand TLD variants, e.g. lidl.be -> lidl.com)
    with KNOWN_GROUP_DOMAINS -- cases where the scanned brand's real sustainability/CSR
    reporting lives mainly on a *different* parent-group domain (e.g. zara.com's group-level
    reporting sits under inditex.com, not under a zara.<tld> variant). Known-group matches are
    checked first since they are the more likely place to find substantive claims."""
    host=(urlparse(url).hostname or '').lower()
    out=[]
    for brand,domains in KNOWN_GROUP_DOMAINS.items():
        if brand in host:
            for d in domains:
                if (urlparse(d).hostname or '') != host and d not in out:
                    out.append(d)
    for c in related_company_sites(url, max_sites=max_sites):
        if c not in out:
            out.append(c)
    return out[:max_sites]

def _canonical_url(url):
    """Normalise a candidate URL for de-duplication without changing its meaning."""
    p=urlparse(url)
    scheme=(p.scheme or 'https').lower()
    host=(p.hostname or '').lower()
    if not host:
        return url
    path=re.sub(r'/+','/',p.path or '/')
    if path != '/':
        path=path.rstrip('/')
    # Marketing/tracking parameters create duplicate candidates without adding content.
    query_parts=[]
    for part in (p.query or '').split('&'):
        if not part: continue
        key=part.split('=',1)[0].lower()
        if key.startswith('utm_') or key in {'gclid','fbclid','mc_cid','mc_eid'}:
            continue
        query_parts.append(part)
    query='&'.join(query_parts)
    return p._replace(scheme=scheme,netloc=host,path=path,query=query,fragment='').geturl()


def _browser_headers(url, accept='text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8', user_agent=None):
    p=urlparse(url)
    origin=f'{p.scheme}://{p.netloc}' if p.scheme and p.netloc else ''
    return {
        'User-Agent': user_agent or CRAWLER_USER_AGENT,
        'Accept': accept,
        'Accept-Language': 'en-GB,en;q=0.9,nl;q=0.7,fr;q=0.6',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Referer': origin+'/' if origin else '',
    }


def _open_public_url(url, timeout=7, accept='text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8', max_bytes=2000000):
    """Open a public URL with browser-like headers and one conservative UA retry.

    The retry is useful for sites that reject one generic browser signature but allow
    another. It does not attempt to bypass authentication, robots rules or access controls.
    """
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname:
        raise ValueError('Invalid URL.')
    if is_private(p.hostname):
        raise ValueError('Private/local URLs are blocked.')
    last_error=None
    for idx,ua in enumerate(BROWSER_USER_AGENTS):
        try:
            req=Request(url,headers=_browser_headers(url,accept,user_agent=ua))
            with urlopen(req,timeout=max(2,timeout),context=ssl.create_default_context()) as r:
                return r.read(max_bytes), r.headers.get('content-type','').lower(), r.geturl()
        except HTTPError as e:
            last_error=e
            # Authentication/permission failures are unlikely to improve through repeated
            # direct requests. Leave them to the optional Reader fallback below.
            if e.code in (401,403,404):
                break
            if e.code not in (408,425,429,500,502,503,504) or idx==len(BROWSER_USER_AGENTS)-1:
                break
            time.sleep(0.15)
        except (URLError, TimeoutError, socket.timeout) as e:
            last_error=e
            if idx==len(BROWSER_USER_AGENTS)-1:
                break
            time.sleep(0.15)
    raise last_error or ValueError('The page could not be retrieved.')


def _reader_url(url):
    # Jina Reader's documented URL-prefix interface accepts a full public URL after
    # https://r.jina.ai/. Quote spaces only; keep URL delimiters intact.
    return 'https://r.jina.ai/'+quote(url, safe=':/?&=%#@+;,')


def fetch_reader_text(url,timeout=9):
    """Optional public-page fallback for blocked or JavaScript-heavy pages.

    Reader returns extracted text/Markdown, not the site's original HTML. It is used only
    when direct retrieval fails or returns a thin shell, and the report diagnostics record
    that fallback method. Set ENABLE_READER_FALLBACK=0 to disable it.
    """
    if not ENABLE_READER_FALLBACK:
        raise ValueError('Reader fallback is disabled.')
    # v86: direct fetches are validated against is_private() via _open_public_url(), but this
    # Reader-fallback path forwarded the URL straight to the external r.jina.ai proxy with no
    # such check. Not a classic SSRF into this app's own network, but it does bypass the
    # explicit "never request private/local URLs" application rule by handing that URL to a
    # third-party fetch service instead of fetching it directly.
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname:
        raise ValueError('Invalid URL.')
    if is_private(p.hostname):
        raise ValueError('Private/local URLs are blocked.')
    headers={
        'User-Agent': CRAWLER_USER_AGENT,
        'Accept': 'text/plain,text/markdown;q=0.9,*/*;q=0.5',
        'X-Return-Format': 'text',
        'X-Timeout': str(max(5,min(20,int(timeout)))),
    }
    if JINA_API_KEY:
        headers['Authorization']='Bearer '+JINA_API_KEY
    req=Request(_reader_url(url),headers=headers)
    try:
        with urlopen(req,timeout=max(3,timeout),context=ssl.create_default_context()) as r:
            raw=r.read(2500000).decode('utf-8',errors='ignore')
    except HTTPError as e:
        # Without JINA_API_KEY the Reader proxy runs on its shared anonymous tier, which can
        # briefly Cloudflare-challenge a request (403) or rate-limit it (429) under load and
        # then serve the same URL fine moments later. One short-delay retry recovers most of
        # these transient hits without materially eating into the overall crawl budget.
        if e.code in (403,429):
            time.sleep(1.2)
            with urlopen(req,timeout=max(3,timeout),context=ssl.create_default_context()) as r:
                raw=r.read(2500000).decode('utf-8',errors='ignore')
        else:
            raise
    # Remove common Reader metadata lines but retain headings and substantive text.
    lines=[]
    for line in raw.splitlines():
        if re.match(r'^(Title|URL Source|Published Time|Markdown Content):\s*',line,re.I):
            continue
        lines.append(line)
    text='\n'.join(lines)
    text=re.sub(r'!\[[^\]]*\]\([^\)]+\)',' ',text)
    text=re.sub(r'\[([^\]]+)\]\([^\)]+\)',r'\1',text)
    text=re.sub(r'[`*_>#|]+',' ',text)
    text='\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip())
    if len(text)<120:
        raise ValueError('Reader fallback returned insufficient usable text.')
    return text[:180000]




def replace_tld_with_be(url):
    """If a .com domain cannot be reached, try the same host with .be."""
    parsed=urlparse(url)
    host=parsed.hostname or ''
    if not host.endswith('.com'):
        return None
    new_host=host[:-4]+'.be'
    netloc=new_host
    if parsed.port:
        netloc += f':{parsed.port}'
    return parsed._replace(netloc=netloc).geturl()


def is_private(host):
    if host in {'localhost','127.0.0.1','0.0.0.0'}: return True
    try:
        for r in socket.getaddrinfo(host,None):
            ip=ipaddress.ip_address(r[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return True
    except Exception: return False
    return False


class _SSRFSafeRedirectHandler(HTTPRedirectHandler):
    """v73: urlopen() follows HTTP redirects automatically, but the app only ever validated the
    ORIGINAL requested hostname against is_private() -- a scanned site that 302-redirects to a
    private/link-local/loopback address (e.g. the cloud metadata endpoint 169.254.169.254, or an
    internal service) would be followed with no re-check, defeating the SSRF guard entirely.
    This handler re-validates every redirect target before it is followed, and is installed as
    the process-wide default opener so it applies to every urlopen() call in the app."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed=urlparse(newurl)
        if parsed.scheme not in ('http','https') or not parsed.hostname:
            raise HTTPError(newurl, code, 'Redirect target is not a valid http(s) URL; blocked.', headers, fp)
        if is_private(parsed.hostname):
            raise HTTPError(newurl, code, 'Redirect target resolves to a private/local address; blocked.', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


install_opener(build_opener(_SSRFSafeRedirectHandler()))


def fetch_html(url,timeout=7):
    data,ctype,_=_open_public_url(url,timeout=timeout,accept='text/html,application/xhtml+xml;q=0.9,*/*;q=0.5',max_bytes=2500000)
    if 'html' not in ctype:
        raise ValueError('URL does not return an HTML page.')
    return data.decode('utf-8',errors='ignore')


def fetch_page_content(url,timeout=7):
    """Retrieve an HTML/PDF page, with an optional Reader fallback for blocked or
    JavaScript-heavy public pages. Returns (text, content_kind, fetch_method, links).

    ``links`` carries the hrefs found on a directly-fetched HTML page (empty for PDFs and
    for Reader-fallback text, which has no reliable link list) so the caller can discover
    pages one hop beyond the initial candidate set -- e.g. a PDF sustainability report that
    is only linked from a "Sustainability" hub page, not from the homepage or the sitemap."""
    direct_error=None
    direct_short_links=[]
    try:
        data,ctype,_=_open_public_url(url,timeout=timeout,max_bytes=5000000)
        if 'pdf' in ctype or url.lower().split('?')[0].endswith('.pdf'):
            text=extract_pdf_text_best_effort(data)
            if len(text)>=80:
                return text,'pdf','direct',[]
            direct_error=ValueError('PDF text extraction returned insufficient content.')
        elif 'html' in ctype:
            raw=data.decode('utf-8',errors='ignore')
            text,page_links=parse_html(raw)
            if len(text)>=THIN_CONTENT_CHARS:
                return text,'html','direct',page_links
            # Keep usable short text, but first try to enrich a likely JS shell via Reader.
            direct_short=text
            direct_short_links=page_links
            direct_error=ValueError('Direct HTML retrieval returned a thin page shell.')
        else:
            direct_error=ValueError('URL does not return an HTML or PDF document.')
    except Exception as e:
        direct_error=e
        direct_short=''
    if ENABLE_READER_FALLBACK and not url.lower().split('?')[0].endswith(('.xml','.txt')):
        try:
            return fetch_reader_text(url,timeout=max(5,min(10,timeout+2))), 'reader', 'reader_fallback', []
        except Exception:
            pass
    if 'direct_short' in locals() and len(direct_short)>=120:
        return direct_short,'html','direct_thin',direct_short_links
    raise direct_error or ValueError('The page could not be retrieved.')


def same_domain(u,base):
    def normalise_host(value):
        value=(value or '').lower().strip('.')
        for prefix in ('www.','m.'):
            if value.startswith(prefix):
                value=value[len(prefix):]
        return value
    h=normalise_host(urlparse(u).hostname or '')
    base=normalise_host(base)
    return bool(h and base) and (h==base or h.endswith('.'+base) or base.endswith('.'+h))


_RELEVANT_SEGMENT_TERMS=('green','planet')
# v84: this list was English-only, so a Dutch or French sustainability hub page (e.g.
# "/nl/duurzaamheid", "/fr/rse") never became a crawl candidate at all -- undercutting the
# NL/FR claim-detection work done earlier this session, which only touched external-search
# queries, not in-site crawl discovery. Direct .pdf links bypass this filter, but the HTML
# hub page that LINKS to the PDF does not, so the PDF itself was often never reached either.
# Includes both accented and unaccented forms since CMS URL slugs go either way.
_RELEVANT_SUBSTRING_TERMS=('sustain','responsib','human','rights','divers','inclusion','supplier','ethic','impact','community','accessibility','safety','annual','report','esg','environment','climate','circular','sourcing','governance','modern-slavery','modern_slavery','non-financial','investor','purpose','society','decarbon','net-zero','net_zero',
    # Dutch
    'duurzaam','verantwoord','mensenrecht','diversiteit','inclusie','leverancier','ethisch','gemeenschap','toegankelijkheid','veiligheid','jaarverslag','milieu','klimaat','circulair','bestuur','dwangarbeid','investeerder','maatschappij','koolstof','mvo',
    # French
    'durable','durabilite','durabilité','responsab','droits-humain','droits_humain','diversite','diversité','fournisseur','ethique','éthique','communaute','communauté','accessibilite','accessibilité','securite','sécurité','rapport-annuel','environnement','climat','circulaire','gouvernance','esclavage-moderne','esclavage_moderne','investisseur','societe','société','decarbon','carbone','rse')
# Retail/grocery sitemaps commonly list product and category-listing URLs, and a product
# name like "Planet Oat Oatmilk" or "Green Beans" trivially matches the sustainability
# keyword list above. Those catalogue pages are structurally distinctive: the final path
# segment is a short catalogue/SKU code (a letter or two followed by digits), unlike a
# genuine content-page slug. Excluding that pattern keeps grocery products out of the
# candidate queue without having to special-case any one retailer's URL scheme.
_CATALOG_ID_SEGMENT_RE=re.compile(r'^[a-z]{1,3}\d{4,}$')

def relevant(h):
    h=h.lower()
    path=urlparse(h).path if '://' in h else h
    last_segment=path.rstrip('/').rsplit('/',1)[-1]
    if _CATALOG_ID_SEGMENT_RE.match(last_segment):
        return False
    if any(k in h for k in _RELEVANT_SUBSTRING_TERMS):
        return True
    # 'green' and 'planet' collide with ordinary grocery/retail product names (e.g.
    # "evergreen", "planetarium") when matched as a raw substring. Require them to appear
    # as a delimited path segment/token instead.
    return any(re.search(r'(?:^|[/_.-])'+term+r'(?:$|[/_.-])',h) for term in _RELEVANT_SEGMENT_TERMS)


COMMON_PUBLIC_PATHS=['/sustainability','/sustainability-report','/csr','/esg','/responsibility',
    '/corporate-responsibility','/corporate-social-responsibility','/human-rights','/supply-chain','/policies','/investors',
    '/investor-relations','/about/sustainability','/about-us/sustainability','/en/sustainability',
    '/our-impact','/planet','/people','/climate','/responsible-sourcing','/news','/press','/newsroom',
    # v84: EN-only common-path guesses meant a Dutch/French site's sustainability hub was only
    # ever found if it happened to be linked/sitemapped -- there was no localized guess to try.
    '/nl/duurzaamheid','/duurzaamheid','/nl/mvo','/mvo','/nl/verantwoord-ondernemen','/nl/over-ons/duurzaamheid',
    '/fr/rse','/rse','/fr/developpement-durable','/developpement-durable','/fr/responsabilite-sociale',
    '/fr/droits-humains','/nl/mensenrechten','/investisseurs','/beleggers','/fr/actualites','/nl/nieuws']


def _fetch_text_document(url,timeout=5,max_bytes=1600000):
    data,ctype,_=_open_public_url(url,timeout=timeout,accept='application/xml,text/xml,text/plain,application/gzip,*/*;q=0.5',max_bytes=max_bytes)
    if data[:2]==b'\x1f\x8b' or 'gzip' in ctype or url.lower().split('?')[0].endswith('.gz'):
        try:
            data=gzip.decompress(data)
        except Exception:
            pass
    return data.decode('utf-8',errors='ignore')


def discover_sitemap_urls(base_url,limit=160,deadline=None):
    """Discover relevant pages from robots.txt and common sitemap locations.

    Supports sitemap indexes and several child sitemaps instead of reading only the first
    child. This substantially improves coverage on multilingual/corporate CMS websites.
    """
    host=urlparse(base_url).hostname or ''
    if not host: return []
    scheme=urlparse(base_url).scheme or 'https'
    sitemap_queue=[]
    try:
        if not deadline or time.time()<deadline:
            t=min(4,max(2,deadline-time.time())) if deadline else 4
            robots=_fetch_text_document(f'{scheme}://{host}/robots.txt',timeout=t,max_bytes=350000)
            sitemap_queue.extend(re.findall(r'^\s*Sitemap:\s*(\S+)',robots,flags=re.I|re.M))
    except Exception:
        pass
    sitemap_queue.extend([
        f'{scheme}://{host}/sitemap.xml',
        f'{scheme}://{host}/sitemap_index.xml',
        f'{scheme}://{host}/sitemap-index.xml',
    ])
    queue=[]; seen_maps=set()
    for u in sitemap_queue:
        u=_canonical_url(u)
        if u not in seen_maps:
            seen_maps.add(u); queue.append((u,0))
    found=[]; seen_urls=set(); processed=0
    while queue and processed<8 and len(found)<limit*3:
        if deadline and time.time()>=deadline-1: break
        sitemap_url,depth=queue.pop(0); processed+=1
        try:
            t=min(5,max(2,deadline-time.time())) if deadline else 5
            body=_fetch_text_document(sitemap_url,timeout=t)
        except Exception:
            continue
        locs=re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',body,flags=re.I)
        is_index='<sitemapindex' in body.lower() or any(x.lower().split('?')[0].endswith(('.xml','.xml.gz')) for x in locs[:5])
        if is_index and depth<1:
            # Rank likely content sitemaps before image/video/news-only indexes.
            locs.sort(key=lambda x:(0 if relevant(x) else 1, 1 if any(k in x.lower() for k in ['image','video']) else 0))
            for child in locs[:6]:
                child=_canonical_url(child)
                if child not in seen_maps:
                    seen_maps.add(child); queue.append((child,depth+1))
            continue
        for u in locs:
            u=_canonical_url(u.strip())
            if same_domain(u,host) and u not in seen_urls:
                seen_urls.add(u); found.append(u)
    # Relevant URLs first; retain a small number of PDFs/reports and avoid non-content assets.
    def score(u):
        low=u.lower(); s=0
        if low.split('?')[0].endswith('.pdf'): s+=80
        for word,weight in [('sustainab',65),('esg',60),('responsib',55),('human-right',55),('modern-slavery',55),('climate',45),('environment',42),('supplier',38),('annual-report',38),('report',25),('people',22),('planet',22),('impact',20),('governance',18)]:
            if word in low: s+=weight
        if any(low.endswith(ext) for ext in ['.jpg','.jpeg','.png','.gif','.svg','.webp','.mp4']): s-=200
        return -s,len(u)
    found.sort(key=score)
    relevant_found=[u for u in found if relevant(u) or u.lower().split('?')[0].endswith('.pdf')]
    return relevant_found[:limit]


THIN_CONTENT_CHARS=400


def _log_fetch_success(log,url,chars,method='direct',source='discovered',content_kind='html'):
    if log is not None:
        log.append({'url':url,'ok':True,'http_status':200,'chars':chars,
                    'thin':chars<THIN_CONTENT_CHARS,'error':None,'method':method,
                    'source':source,'content_kind':content_kind})


def _log_fetch_failure(log,url,err,source='discovered'):
    if log is not None:
        code=err.code if isinstance(err,HTTPError) else None
        log.append({'url':url,'ok':False,'http_status':code,'chars':0,'thin':False,
                    'error':_describe_fetch_error(err),'method':'failed','source':source})


def _candidate_score(item):
    url,source=item
    low=url.lower(); score=0
    if source=='linked': score+=35
    elif source=='sitemap': score+=25
    elif source=='common_path': score-=5
    if low.split('?')[0].endswith('.pdf'): score+=70
    # v87: this scoring list was English-only, so a Dutch/French sustainability candidate that
    # DID pass the relevant() filter (NL/FR terms were added there earlier) still scored no
    # keyword credit here, only the flat source-type bonus -- systematically pushing it toward
    # the bottom of the ranked queue and toward the CRAWL_MAX_PAGE_ATTEMPTS cutoff whenever it
    # competed against English or common-path candidates. Added NL/FR terms at the same weights
    # as their English equivalents.
    for word,weight in [('sustainab',55),('esg',50),('responsib',45),('human-right',45),('modern-slavery',45),('climate',38),('environment',35),('supplier',32),('annual',25),('report',24),('people',18),('planet',18),('impact',16),('governance',15),
        ('duurzaam',55),('verantwoord',45),('mensenrecht',45),('moderne-slavernij',45),('klimaat',38),('milieu',35),('leverancier',32),('jaarverslag',25),('mensen',18),('planeet',18),('bestuur',15),
        ('durabilite',55),('durable',55),('responsab',45),('droits-humain',45),('esclavage-moderne',45),('climat',38),('environnement',35),('fournisseur',32),('annuel',25),('rapport',24),('personnes',18),('planete',18),('gouvernance',15)]:
        if word in low: score+=weight
    return -score,len(url)


def crawl(url,max_extra_pages=None,deadline=None,log=None,candidate_source='primary'):
    """Crawl the homepage and continue through a ranked candidate queue until the target
    number of usable extra pages is reached. Individual failures no longer consume the whole
    page allowance."""
    max_extra_pages=max_extra_pages or CRAWL_TARGET_EXTRA_PAGES
    if deadline is None:
        deadline=time.time()+CRAWL_BUDGET_SECONDS
    def remaining(): return max(1,deadline-time.time())

    # Homepage: direct HTML first so internal links can be discovered; Reader fallback if the
    # direct request is blocked. Reader text cannot provide a reliable link list.
    homepage_method='direct'; links=[]
    try:
        html=fetch_html(url,timeout=min(7,remaining()))
        text,links=parse_html(html)
        if len(text)<THIN_CONTENT_CHARS and ENABLE_READER_FALLBACK and remaining()>4:
            try:
                reader_text=fetch_reader_text(url,timeout=min(9,remaining()))
                if len(reader_text)>len(text):
                    text=reader_text; homepage_method='reader_fallback'
            except Exception:
                homepage_method='direct_thin'
    except Exception as direct_error:
        if ENABLE_READER_FALLBACK and remaining()>3:
            try:
                text=fetch_reader_text(url,timeout=min(9,remaining())); homepage_method='reader_fallback'
            except Exception:
                _log_fetch_failure(log,url,direct_error,source='homepage')
                raise direct_error
        else:
            _log_fetch_failure(log,url,direct_error,source='homepage')
            raise
    _log_fetch_success(log,url,len(text),method=homepage_method,source='homepage',content_kind='html')
    host=urlparse(url).hostname or ''
    pages=[url]; chunks=[text]

    candidates=[]; seen={_canonical_url(url)}
    def add_candidate(candidate,source,allow_cross_domain=False):
        candidate=_canonical_url(candidate.split('#')[0])
        if not candidate or candidate in seen: return
        if not allow_cross_domain and not same_domain(candidate,host): return
        seen.add(candidate); candidates.append((candidate,source))

    for href in links:
        full=urljoin(url,href)
        is_pdf=full.lower().split('?')[0].endswith('.pdf')
        # A report PDF is very often hosted off the company's own domain -- on a CMS/asset
        # CDN (e.g. cdn.sanity.io, Cloudinary, an S3/CloudFront bucket) rather than the site
        # itself. It is fetched read-only for text extraction, not crawled further (a PDF
        # never yields further link candidates), so trusting a PDF link placed on the
        # company's own page carries the same risk as any other page content review.
        if relevant(full) or is_pdf:
            add_candidate(full,'linked',allow_cross_domain=is_pdf)

    if time.time()<deadline-2:
        try:
            # A retail/grocery site's sitemap index can have several large child sitemaps
            # (product/category listings), and discover_sitemap_urls() fetches up to 8 of
            # them sequentially. Handing it the full crawl deadline let that sequential
            # fetching alone consume the entire remaining budget on some sites before a
            # single actual page got fetched below -- crawl() would then return just the
            # homepage with no failed attempts logged (nothing else was ever tried, not
            # even the unconditional COMMON_PUBLIC_PATHS candidates a few lines down).
            # Cap discovery to a bounded slice of whatever time is left so the page-fetch
            # loop always keeps a guaranteed share of the budget.
            sitemap_deadline=min(deadline,time.time()+max(4,min(10,remaining()*0.5)))
            for u in discover_sitemap_urls(url,deadline=sitemap_deadline):
                add_candidate(u,'sitemap')
        except Exception:
            pass

    scheme=urlparse(url).scheme or 'https'
    for path in COMMON_PUBLIC_PATHS:
        add_candidate(f'{scheme}://{host}{path}','common_path')

    candidates.sort(key=_candidate_score)
    candidates=candidates[:CRAWL_MAX_PAGE_ATTEMPTS]
    successful=0
    cursor=0
    attempts=0
    # Modest headroom beyond the level-1 budget for pages discovered one hop deeper (see below)
    # -- reports are frequently linked only from a Sustainability/CSR hub page, not the homepage
    # or the sitemap, so without this a valid PDF found there would otherwise go unfetched.
    max_attempts=CRAWL_MAX_PAGE_ATTEMPTS+8
    # Small parallel batches prevent two slow/blocked pages from exhausting the entire crawl
    # budget while keeping request concurrency modest for the target site.
    while cursor<len(candidates) and successful<max_extra_pages and attempts<max_attempts and time.time()<deadline-2:
        batch=candidates[cursor:cursor+CRAWL_FETCH_WORKERS]; cursor+=len(batch); attempts+=len(batch)
        per_timeout=min(8,max(3,remaining()-1))
        discovered=[]
        with ThreadPoolExecutor(max_workers=min(CRAWL_FETCH_WORKERS,len(batch))) as executor:
            futures={executor.submit(fetch_page_content,u,per_timeout):(u,source) for u,source in batch}
            for future in as_completed(futures):
                link,source=futures[future]
                try:
                    t,kind,method,page_links=future.result()
                    min_chars=80 if kind=='pdf' else 120
                    if len(t)>min_chars:
                        _log_fetch_success(log,link,len(t),method=method,source=source,content_kind=kind)
                        if successful<max_extra_pages:
                            label='REPORT (PDF): ' if kind=='pdf' else 'PAGE: '
                            chunks.append('\n\n'+label+link+'\n'+t)
                            pages.append(link); successful+=1
                        for href in page_links:
                            full=urljoin(link,href)
                            is_pdf=full.lower().split('?')[0].endswith('.pdf')
                            if relevant(full) or is_pdf:
                                cand=_canonical_url(full.split('#')[0])
                                if cand and cand not in seen and (is_pdf or same_domain(cand,host)):
                                    seen.add(cand); discovered.append((cand,'linked_2nd'))
                    else:
                        _log_fetch_failure(log,link,ValueError('The page returned insufficient usable text.'),source=source)
                except Exception as e:
                    _log_fetch_failure(log,link,e,source=source)
        if discovered:
            discovered.sort(key=_candidate_score)
            candidates[cursor:cursor]=discovered[:max(0,max_attempts-attempts)]
    return '\n\n'.join(chunks)[:150000], pages

COMPANY_SUFFIXES=r'(?:Corp\.?|Inc\.?|Ltd\.?|LLC|LLP|PLC|N\.?V\.?|S\.?A\.?|B\.?V\.?|GmbH|AG|SE|Group|Holdings?|Company|Co\.?|Limited)'
_NAME_CAP=r'A-ZÀ-ÖØ-Þ'
_NAME_CONT=r'A-Za-z0-9À-ÖØ-öø-ÿ'
_COMPANY_NAME_RE=re.compile(r'\b(['+_NAME_CAP+r']['+_NAME_CONT+r'&\'\.\-]*(?:\s+['+_NAME_CAP+r']['+_NAME_CONT+r'&\'\.\-]*){0,3}\s+'+COMPANY_SUFFIXES+r')\b')

def _guess_company_from_text(text):
    """Best-effort text-mining fallback for document uploads with no domain to infer from:
    looks for a capitalized name immediately followed by a common corporate suffix
    (e.g. 'Acme Corp', 'Acme Group N.V.') within the first part of the document."""
    m=_COMPANY_NAME_RE.search((text or '')[:3000])
    if m:
        name=re.sub(r'\s+',' ',m.group(1)).strip()
        if 2 <= len(name) <= 60:
            return name
    return ''

def infer_sector(company,text,page_segments=None,homepage_url=None):
    if company.get("sector_risk"):
        level=company["sector_risk"]; basis="recognised company/sector profile"
    else:
        # v86: sector was inferred from the first 15,000 chars of the ENTIRE crawled corpus
        # (every page concatenated), taking the FIRST tier (High wins outright over Medium/Low)
        # with even a single matching word anywhere. Reproduced: "Our software platform helps
        # customers track coffee deliveries" and "We provide professional services to
        # supermarkets" both classified as High sector risk purely from one incidental mention
        # of the company's CLIENTS' business, not its own. Two changes: (1) prefer the
        # homepage/about-style content when page-level segments are available -- that's where a
        # company actually describes what it does, not a page deep in the site about a client
        # or topic; (2) the High tier (the most consequential, and the one most vulnerable to a
        # single incidental word) now requires at least 2 distinct matching terms, not 1, before
        # it can override a Medium/Low match.
        # v87: page_segments[0] is NOT always the scanned company's own homepage --
        # crawl_with_related_sites() only appends the primary domain's pages to `all_pages` when
        # its crawled text is non-whitespace (`if txt.strip():`); a JS-rendered/SPA homepage that
        # parse_html can't extract text from leaves `all_pages` starting with a RELATED/group
        # domain's pages instead, so "the first segment" could describe a different company
        # entirely. Match on the actual scanned hostname when available, falling back to
        # position 0 only when that hostname can't be found in the segments (e.g. the
        # single-document-scan path, which has no real "homepage" concept anyway).
        homepage_text=''
        if page_segments:
            target_host=(urlparse(homepage_url).hostname or '').lower().removeprefix('www.') if homepage_url else ''
            match=None
            if target_host:
                for seg in page_segments:
                    seg_host=(urlparse(str(seg.get('url') or '')).hostname or '').lower().removeprefix('www.')
                    if seg_host==target_host:
                        match=seg; break
            homepage_text=(match or page_segments[0]).get('text','') or ''
        lower=(company.get("sector","")+" "+(homepage_text[:8000] if homepage_text else text[:15000])).lower()
        level="Medium"; basis="default medium exposure"
        for lvl,terms,risks in SECTOR_RULES:
            hits=[t for t in terms if t in lower]
            if hits and (lvl!="High" or len(hits)>=2):
                level=lvl; basis="matched terms: "+", ".join(hits[:5]); break
    risks=next(r for lvl,terms,r in SECTOR_RULES if lvl==level)
    return {"level":level,"basis":basis,"risks":risks}

def google_search(query, max_results=5):
    """Google Custom Search JSON API fallback. Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return []
    from urllib.parse import urlencode
    params=urlencode({"key":GOOGLE_SEARCH_API_KEY,"cx":GOOGLE_SEARCH_CX,"q":query,"num":max(1,min(max_results,10))})
    req=Request("https://www.googleapis.com/customsearch/v1?"+params,headers={"User-Agent":CRAWLER_USER_AGENT},method="GET")
    try:
        with urlopen(req,timeout=7) as r:
            data=json.loads(r.read().decode("utf-8",errors="ignore"))
    except HTTPError as e:
        # v89: same fix as serper_search() -- surface Google's actual JSON error body (e.g. "API
        # not enabled for this project", "Daily Limit Exceeded", an invalid CX/key message)
        # instead of the bare "HTTP Error 403: Forbidden" status line.
        try: body=e.read().decode("utf-8",errors="ignore")[:300].strip()
        except Exception: body=""
        raise ValueError(f'HTTP Error {e.code}: {body or e.reason or "(no error body)"}') from e
    out=[]
    # v84: was a flat 0, while Tavily returns a native 0-1 relevance score and Serper computes
    # one from rank (1.0/position). When multiple providers are merged and sorted by score
    # before the pre-filter cap in search_public_sources(), a flat 0 meant Google's results
    # were provably always sorted last and the first to be dropped -- structurally silencing
    # that provider whenever others were also configured. Google's JSON API doesn't return a
    # relevance score, but result order IS rank order, so derive one the same way Serper does.
    for i,item in enumerate(data.get("items",[]),start=1):
        out.append({"title":item.get("title",""),"url":item.get("link",""),"content":item.get("snippet",""),"score":1.0/i,"provider":"Google Custom Search"})
    return out


def query_themes_from_findings(findings):
    # v77: NL/FR baseline themes go first (in an order-preserving list, not a set -- a set
    # would not guarantee they survive the [:9] cap below) so a company whose real press
    # coverage is mainly Dutch or French (common across the Benelux/France market) still gets
    # searched in those languages -- see the matching note on green_query_themes().
    themes=["dwangarbeid misstanden arbeidsomstandigheden klacht", "travail forcé plainte conditions de travail"]
    joined=" ".join((f.get("type","")+" "+f.get("claim","")).lower() for f in (findings or []))
    if "supplier" in joined or "supply" in joined: themes += ["supplier labour rights controversy", "forced labour supply chain", "audit failure worker voice remediation", "workers wage complaint", "NGO labour rights report", "EU forced labour regulation supply chain product import"]
    if "forced" in joined or "modern slavery" in joined: themes += ["forced labour products regulation investigation", "modern slavery supply chain import ban", "forced labour product withdrawal customs EU"]
    if "human" in joined or "labour" in joined or "labor" in joined: themes += ["human rights complaint", "labour rights lawsuit", "modern slavery forced labour", "workers rights NGO report"]
    if "diversity" in joined or "inclusion" in joined or "equality" in joined: themes += ["discrimination lawsuit", "diversity inclusion controversy", "pay gap equal opportunity complaint"]
    if "safety" in joined or "worker" in joined or "welfare" in joined: themes += ["worker safety accident", "union strike working conditions", "employee welfare complaint"]
    if "customer" in joined or "accessibility" in joined or "vulnerable" in joined: themes += ["customer protection regulator complaint", "accessibility complaint", "vulnerable customers investigation"]
    if "community" in joined or "impact" in joined: themes += ["community impact criticism", "affected communities complaint", "social impact controversy"]
    if len(themes) <= 2:
        themes += ["social responsibility criticism", "human rights labour controversy", "workers supplier complaint"]
    return list(dict.fromkeys(themes))[:9]


def summarise_ext(results):
    if not results: return "No external public-source results were returned."
    combo=" ".join((r.get("title","")+" "+r.get("content","")).lower() for r in results)
    terms=["forced labour","forced labor","eu forced labour regulation","product ban","import ban","child labour","child labor","lawsuit","complaint","strike","union","ngo","discrimination","human rights","supplier","workers","controversy","regulator","customs","withdrawal"]
    hits=[t for t in terms if t in combo]
    return ("External results contain potentially relevant social-risk signals, including: "+", ".join(hits[:8])+". These require verification.") if hits else "External results were found, but no strong social-risk signal was detected from snippets alone."
def infer_context(company,text,ext):
    combo=(company.get("context","")+" "+text[:20000]+" "+ext.get("summary","")).lower(); level="Medium" if "No recognised" not in company.get("context","") else "Low"
    high=["forced labour","forced labor","eu forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","living wage","lawsuit","strike","union","human rights complaint","discrimination","regulator"]
    med=["complaint","supplier","workers","controversy","ngo","accessibility","vulnerable customers","subcontractor","franchise"]
    if any(t in combo for t in high): level="Medium" if level=="Low" else level
    elif any(t in combo for t in med) and level=="Low": level="Medium"
    note=company.get("context","")+" External public-source layer: "+ext.get("summary","")
    return {"level":level,"note":note.strip()}

def build_entity_context_indicator(sector, ctx, green_targeted, social_targeted, external_verification_status):
    """v57p: shown separately from (and never blended into) the green/social claim communication
    scores. A company's sector exposure or a public controversy is relevant context for a
    reviewer, but is not itself proof that a specific detected claim is misleading -- collapsing
    both into one number risks presenting a serious entity-level incident as if it were evidence
    against a particular piece of wording. This indicator makes that distinction visible."""
    total_external=len(green_targeted or [])+len(social_targeted or [])
    levels={'Low':0,'Medium':1,'High':2,'Very high':3}
    sector_lvl=levels.get((sector or {}).get('level','Low'),0)
    ctx_lvl=levels.get((ctx or {}).get('level','Low'),0)
    signal_lvl=2 if total_external>=3 else (1 if total_external>=1 else 0)
    combined=max(sector_lvl,ctx_lvl,signal_lvl)
    label={0:'Low',1:'Elevated',2:'High',3:'Very high'}[combined]
    parts=[]
    if total_external:
        parts.append(f"{total_external} external public-source signal(s) were retained and may be relevant to the credibility of the assessed claims, subject to manual verification.")
    else:
        parts.append("No external public-source signal was retained.")
    if (sector or {}).get('level') in ('High','Very high'):
        basis=((sector or {}).get('risks','') or '')[:180]
        parts.append(f"Sector exposure is {sector.get('level')}"+(f": {basis}" if basis else "."))
    return {'level':label,'note':' '.join(parts),'external_signals_retained':total_external,
            'sector_exposure':(sector or {}).get('level','Low'),'context_level':(ctx or {}).get('level','Low'),
            'external_verification_status':external_verification_status,
            'explanation':'This indicator reflects company/sector exposure and retained external public-source signals. It is shown separately from the green and social claim-communication scores and is not blended into them, so an entity-level incident is not automatically presented as proof that a specific claim is misleading.'}
def snip(text,trig):
    return clean_excerpt(text,trig)


LOW_RISK_SUPPLIER_CONTEXTS = [
    'backing british suppliers','supporting british suppliers','supporting local suppliers','support local suppliers',
    'backing local suppliers','local suppliers','british suppliers','working with suppliers','our suppliers include'
]
SUPPLIER_RESPONSIBILITY_QUALIFIERS = [
    'responsible','ethical','sustainable','sustainability','human rights','labour rights','labor rights','forced labour','forced labor',
    'child labour','child labor','modern slavery','living wage','traceable','traceability','certified','audited','audit','due diligence',
    'supplier code','code of conduct','compliant','compliance','remediation','grievance','fair','transparent','transparency',
    'tier 1','tier 2','all suppliers','every supplier','supply chain','value chain','sourcing','procurement'
]

def _context_window(text, start, end, chars=120):
    return (text[max(0,start-chars):min(len(text),end+chars)] or '')

def _is_supplier_responsibility_context(text, trigger, pos):
    """Avoid false positives where 'supplier(s)' is used neutrally.
    A supplier reference is scored only when the surrounding wording implies responsibility, traceability,
    certification, audit coverage, human-rights/labour controls, due diligence or absolute supplier coverage.
    """
    low=text.lower(); trig=trigger.lower(); end=pos+len(trig)
    win=_context_window(low,pos,end,170)
    # Use the single sentence containing the trigger (not the wider window, which can bleed
    # into an adjacent sentence and smuggle in assertion language that isn't actually about
    # this trigger) to check whether this is just a bare document-title reference.
    sentence_excerpt=_v55_sentence_list(text,trigger).lower()
    if _looks_like_bare_document_title(sentence_excerpt):
        return False
    # Explicit high-sensitivity phrases remain valid.
    explicit=['supply chain','value chain','all suppliers','every supplier','responsible sourcing','ethical sourcing','supplier code','supplier standards','supplier due diligence','supplier traceability','human rights in the supply chain','supply-chain transparency','audited suppliers','certified suppliers','traceable suppliers']
    if any(x in win for x in explicit):
        return True
    # Bare supplier(s) + neutral local-support wording is not a social-washing claim.
    if trig in ['supplier','suppliers']:
        if any(x in win for x in LOW_RISK_SUPPLIER_CONTEXTS) and not any(q in win for q in SUPPLIER_RESPONSIBILITY_QUALIFIERS if q not in ['sourcing','procurement']):
            return False
        return any(q in win for q in SUPPLIER_RESPONSIBILITY_QUALIFIERS)
    # Other triggers need claim-like context, not isolated technical wording.
    if trig in ['audited','certified','traceable']:
        return any(x in win for x in ['supplier','suppliers','supply chain','product','products','source','sourcing','materials','cotton','factory','factories'])
    return True

def _find_valid_trigger(text, triggers, claim_type):
    low=text.lower()
    for trig in triggers:
        start=0
        while True:
            i=low.find(trig.lower(), start)
            if i < 0:
                break
            if claim_type == 'Supply-chain or supplier-responsibility claim' and not _is_supplier_responsibility_context(text, trig, i):
                start=i+len(trig)
                continue
            return trig
    return None

def problematic_terms_for_finding(claim_text, claim_type=''):
    """Return short list of words/phrases that explain why a detected claim was flagged."""
    terms=[
        'green','eco','ecological','environmentally friendly','natural','sustainable','sustainability','climate neutral','carbon neutral','co2 neutral','co₂ neutral','net zero','carbon positive','carbon negative','climate positive','offset','offsetting','climate compensated','reduced climate impact','biodegradable','recyclable','recycled','circular','renewable','green energy','energy efficient','water efficient','better for the planet','greener than','more sustainable than','lower emissions','reduced emissions','lowest emissions','best environmental','ethical','fair','responsible','socially responsible','trusted','human rights','labour rights','labor rights','forced labour','forced labor','child labour','child labor','modern slavery','living wage','supply chain','supplier','responsible sourcing','ethical sourcing','traceable','certified','audited','diversity','inclusion','inclusive','safe workplace','well-being','accessibility','vulnerable customers','for all','all suppliers','all employees','100%','always','never','guarantee','fully','zero'
    ]
    low=(claim_text or '').lower(); out=[]
    for t in terms:
        if t in low and t not in out:
            out.append(t)
    # Add claim-type markers where the excerpt is too short or lacks the exact trigger term.
    ct=(claim_type or '').lower()
    for marker in ['generic environmental claim','climate-neutrality or offsetting claim','sustainability label / certification claim','future environmental-performance claim','comparative environmental claim','forced-labour product or supply-chain claim','supply-chain or supplier-responsibility claim','broad ethical or responsible-business claim']:
        if marker.lower() in ct and marker not in out:
            out.append(marker)
    # Avoid showing bare supplier/suppliers as a problematic term unless the claim type is genuinely about supplier responsibility or forced labour.
    if 'supplier' not in (claim_type or '').lower() and 'forced' not in (claim_type or '').lower():
        out=[x for x in out if x not in ['supplier','suppliers']]
    return out[:10]

def level(score):
    # v88: rebalanced to four EQUAL 25-point bands (0-24/25-49/50-74/75-100). The previous
    # bands (0-44/45-74/75-89/90-100) gave "Low" a 45-point catch-all range nearly three times
    # wider than "High" (15 points) or "Very high" (11 points) -- a company with several
    # High-risk EmpCo Annex I-category claims (claim_wording_risk maxed at 100/100) could still
    # land at a raw score in the low-to-mid 40s purely from the blended formula, and the
    # lopsided bands then labelled that "Low" instead of "Medium".
    return "Very high" if score>=75 else "High" if score>=50 else "Medium" if score>=25 else "Low"
def external_relevance_score(findings, external_research):
    """
    V24 calibrated external modifier:
    - External signals are capped and only lift the score when relevant to the company and claim themes.
    - External context is a modifier, not a replacement for website claim analysis.
    """
    if not external_research or not external_research.get("enabled"):
        return 0, "No external-source modifier applied because external search is not enabled."

    text = " ".join((r.get("title","") + " " + r.get("content","") + " " + r.get("url","")).lower()
                    for r in external_research.get("results", []))
    if not text.strip():
        return 0, "External search returned no usable source signals."

    claim_text = " ".join((f.get("type","") + " " + f.get("issue","")).lower() for f in findings)

    severe_terms = ["forced labour","forced labor","eu forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","human rights complaint","lawsuit","court","regulator","regulatory","discrimination","strike","union","living wage"]
    relevant_terms = ["human rights","labour","labor","workers","supplier","supply chain","accessibility","customer protection","discrimination","grievance","complaint","ngo","oecd","ncp","audit","wage","safety"]

    severe_hits = [t for t in severe_terms if t in text]
    relevant_hits = [t for t in relevant_terms if t in text]

    thematic_match = False
    if ("supplier" in claim_text or "supply" in claim_text) and any(t in text for t in ["supplier","supply chain","forced labour","forced labor","child labour","child labor","audit","wage"]):
        thematic_match = True
    if ("human" in claim_text or "labour" in claim_text or "labor" in claim_text) and any(t in text for t in ["human rights","labour","labor","workers","forced labour","forced labor","living wage"]):
        thematic_match = True
    if ("customer" in claim_text or "accessibility" in claim_text) and any(t in text for t in ["customer protection","accessibility","vulnerable customers","complaint"]):
        thematic_match = True
    if ("diversity" in claim_text or "inclusion" in claim_text) and any(t in text for t in ["discrimination","equality","diversity","inclusion"]):
        thematic_match = True
    if ("worker" in claim_text or "safety" in claim_text) and any(t in text for t in ["workers","safety","strike","union","wage","labour","labor"]):
        thematic_match = True

    score = 0
    if relevant_hits:
        score += 3
    if len(relevant_hits) >= 3:
        score += 3
    if severe_hits:
        score += 5
    if thematic_match:
        score += 4
    if len(severe_hits) >= 2 and thematic_match:
        score += 3

    score = min(score, 18)
    if score == 0:
        note = "External sources were found but did not materially align with the detected social-claim risk areas."
    else:
        note = "External-source modifier applied because public-source signals appear relevant to the company and claim areas: " + ", ".join((severe_hits + relevant_hits)[:8]) + "."
    return score, note

def is_placeholder_finding(finding_type):
    """True for the synthetic "no claim retained" row detect_green_claims()/detect_claims()
    append when nothing material was found. That row's actual type string is "No material
    problematic {green,social} claim retained" -- but a large fraction of the functions in
    this file that need to detect it were checking only startswith('no major'), a string no
    code path has generated in a long time, which never matched. Each of those was silently
    always treating "no findings" the same as a real, material claim (spurious evidence-gap
    analysis, phantom pre-publication-review rows, phantom claim-module/signal counts). Use
    this single helper everywhere instead of re-implementing the prefix check ad hoc."""
    t = (finding_type or '').lower()
    return t.startswith('no material') or t.startswith('no major')


def evidence_signal_score(page_text, findings):
    """
    V25: evidence is assessed only in the original crawled website text, not in generated
    recommendations. This avoids giving credit for wording that the tool itself produced.
    """
    text=(page_text or "").lower()
    if not text.strip() or (findings and is_placeholder_finding(findings[0].get("type",""))):
        return 75, ["No major claim detected; evidence gap is not the main driver."]
    strong_terms=[
        "kpi","kpis","metric","metrics","indicator","baseline","target","targets","percentage","%",
        "reporting period","scope","coverage","audit coverage","supplier tier","tier 1","tier 2",
        "grievance mechanism","complaints mechanism","remediation","remedy","corrective action",
        "closure rate","due diligence","salient human rights","worker voice","collective bargaining",
        "pay equity","incident rate","lost time injury","ltir","assurance","verified","independent audit",
        "limited assurance","reasonable assurance","methodology","limitations","exclusions",
        "traceability","chain of custody","supplier traceability","product traceability","import controls","export controls",
        "forced-labour risk assessment","forced labour risk assessment","modern slavery statement",
        "withdrawal procedure","customs procedure","remediation plan"
    ]
    weak_terms=["policy","policies","commitment","principles","code of conduct","training","programme","program","progress","initiative"]
    strong_hits=[t for t in strong_terms if t in text]
    weak_hits=[t for t in weak_terms if t in text]
    # Numeric data near social terms is a strong substantiation proxy.
    import re
    social_window_terms=["supplier","worker","employee","human rights","diversity","inclusion","safety","customer","community","labour","labor","forced labour","forced labor","modern slavery","traceability","import","export","product"]
    numeric_social_hits=0
    for m in re.finditer(r'(\b\d{1,4}(?:[.,]\d+)?\s?%\b|\b20\d{2}\b)', text):
        win=text[max(0,m.start()-160):m.end()+160]
        if any(t in win for t in social_window_terms): numeric_social_hits+=1
    points=min(55,len(strong_hits)*7)+min(15,len(weak_hits)*3)+min(20,numeric_social_hits*5)
    substantiation=min(100,points)
    if substantiation>=75: level_note="Concrete website evidence was found for several claim-quality elements."
    elif substantiation>=45: level_note="Some website evidence was found, but important scope, KPI or remediation details may still be missing."
    elif substantiation>=20: level_note="Limited website evidence was found; broad claims should be better substantiated."
    else: level_note="Little concrete website evidence was found around detected social claims."
    hits=(strong_hits[:8]+weak_hits[:4]) or ["no concrete evidence terms detected"]
    return substantiation, [level_note, "Detected evidence indicators: "+", ".join(hits)+"."]

def evidence_quality_credit(page_text, findings):
    substantiation, _ = evidence_signal_score(page_text, findings)
    if substantiation >= 75: return 12
    if substantiation >= 55: return 8
    if substantiation >= 35: return 4
    return 0

def washing_conclusion(score, findings, evidence_gap, external_score):
    no_major = findings and is_placeholder_finding(findings[0].get("type",""))
    if no_major:
        return "No clear social-washing signal detected"
    if score < 30:
        return "Low substantiation risk"
    if score < 50:
        return "Potentially overbroad social claim"
    if score < 60:
        return "Potential social-washing concern  -  evidence review needed"
    if external_score >= 40 and evidence_gap >= 55:
        return "High social-washing risk signal  -  verify urgently"
    return "Potential social-washing concern  -  not enough contradiction evidence for High"


def guidance(findings,sector):
    txt=" ".join(f["rewrite"] for f in findings[:2])
    if sector["level"]=="High": txt+=" Because this sector has higher structural exposure, avoid generic wording such as 'ethical', 'fair', 'responsible' or 'for everyone' unless scope, coverage, limitations and remediation evidence are explicit."
    return txt
def build_report(company,sector,context,findings,score,pages):
    top=", ".join(f["type"] for f in findings[:3])
    high_claims=[f for f in findings if f["risk"]=="High"]
    if high_claims:
        driver="claim wording that may overstate social performance, coverage, control or substantiation"
    else:
        driver="mainly moderate claim wording, with no clear high-risk social-washing wording detected"
    summary=f"{company['company']} receives a {level(score).lower()} social-claim risk score of {score}/100. The score is primarily based on actual wording found on the reviewed company pages, especially {top}. Relevant external public-source signals may materially increase the score when they relate to the same company and the same social-risk themes. The main improvement is to make broad social claims more specific, measurable and evidence-backed."
    rationale=f"Claim focus: the rating gives most weight to website wording that could create an unsupported impression of social performance. Sector context: {sector['risks']} Basis: {sector['basis']}. Public-source context: {context['note']} External signals are considered more strongly when they are relevant to the concrete company and align with detected claim themes such as workers, suppliers, human rights, inclusion, customer protection or communities."
    return {"summary":summary,"rationale":rationale,"rewrite_guidance":guidance(findings,sector),"pages_reviewed":pages,"standards_overview":STANDARDS,"scoring_note":""}


def evidence_checklist(f):
    t=(f.get("type","")+" "+f.get("issue","")).lower()
    base=["scope of the claim","reporting period","underlying policy or process","metrics or KPIs","limitations and exclusions"]
    if "forced" in t or "modern slavery" in t: return base+["forced-labour risk assessment by product and geography","supplier and product traceability","import/export and withdrawal response procedure","worker voice or grievance mechanism","remediation and disengagement criteria","governance owner for Regulation (EU) 2024/3015 readiness"]
    if "supply" in t or "supplier" in t: return base+["supplier-tier coverage","audit/assessment methodology","forced-labour risk assessment where relevant","worker voice or grievance mechanism","corrective-action closure rate","remediation examples"]
    if "human" in t or "labour" in t or "labor" in t: return base+["salient human-rights risk assessment","due-diligence steps","forced-labour risk controls where products/supply chains are relevant","grievance channels","tracking of outcomes","remedy process"]
    if "diversity" in t or "inclusion" in t: return base+["workforce diversity data","baseline and targets","pay-equity data where relevant","employee feedback","progress against action plan"]
    if "customer" in t or "accessibility" in t: return base+["customer outcome metrics","complaint data","vulnerable-customer safeguards","accessibility measures","remedy process"]
    if "safety" in t or "worker" in t: return base+["incident rates","contractor coverage","training data","safety audit results","corrective actions"]
    return base+["evidence trail","methodology","governance owner"]

def build_claim_inventory(findings):
    return [{"claim_text":f.get("claim",""),"claim_type":f.get("type",""),"risk_level":f.get("risk",""),"claim_score":f.get("claim_score",0),"risk_reason":f.get("issue",""),"matched_phrase":f.get("matched_phrase",""),"why_flagged":f.get("why_flagged",""),"regulatory_signal":f.get("regulatory_signal",""),"specification_check":f.get("specification_check",{}),"pre_publication_decision":f.get("pre_publication_decision","Review before publication."),"evidence_needed":evidence_checklist(f),"suggested_rewrite":f.get("rewrite",""),"standards":f.get("standards",[]),"problematic_terms":f.get("problematic_terms",[]),"blacklisted_practice_indicator":f.get("blacklisted_practice_indicator",False),"legal_basis_category":f.get("legal_basis_category","problematic"),"legal_basis_label":f.get("legal_basis_label",""),"ready_to_use_rewrite":f.get("ready_to_use_rewrite","")} for f in findings]

def build_red_flags(findings,ext,sector,context):
    flags=[]
    if any(f.get("risk")=="High" for f in findings): flags.append("Broad or high-sensitivity social claims appear on the website and may require stronger substantiation.")
    if any(("supplier" in f.get("type","").lower() or "supply" in f.get("type","").lower()) for f in findings): flags.append("Supply-chain wording should be checked against supplier coverage, audit quality, worker voice and remediation evidence.")
    if any(("forced" in f.get("type","").lower() or "modern slavery" in f.get("type","").lower()) for f in findings): flags.append("EU Forced Labour Regulation readiness & substantiation flag (Regulation (EU) 2024/3015; core prohibition and enforcement provisions apply from 14 December 2027): forced-labour or modern-slavery wording should not imply product/supply-chain assurance unless product/supplier traceability, risk assessment, remediation and withdrawal/customs response readiness are evidenced.")
    if any(("human" in f.get("type","").lower() or "labour" in f.get("type","").lower() or "labor" in f.get("type","").lower()) for f in findings): flags.append("Human-rights or labour-rights claims require evidence of due diligence, grievance channels and remedy.")
    if ext.get("enabled") and ext.get("results"): flags.append("External public-source signals were found and should be verified before relying on the company's wording.")
    if sector.get("level")=="High": flags.append("The sector has structurally higher exposure to labour, supplier, worker or vulnerable-stakeholder issues.")
    if context.get("level") in ["High","Very high"]: flags.append("Company/context sensitivity is elevated and should be considered in stakeholder due diligence.")
    if not flags: flags.append("No major red flag was detected from available website and public-source signals, but manual verification remains necessary.")
    return flags[:6]

def regulatory_red_flags(green_findings, social_findings, audience):
    """Add explicit regulatory red flags where the claim wording falls directly under EmpCo or the EU Forced Labour Regulation lens."""
    flags=[]
    aud=(audience or {}).get('audience','').lower()
    direct_consumer=('client-facing' in aud or 'consumer-facing' in aud or 'mixed' in aud)
    for f in green_findings or []:
        typ=(f.get('type','')+' '+f.get('issue','')+' '+f.get('claim','')).lower()
        if f.get('risk')=='High' and direct_consumer and any(t in typ for t in ['generic environmental','climate-neutrality','offset','comparative','future environmental','absolute','sustainable','greenwashing','empco']):
            flags.append('EmpCo readiness flag (Directive (EU) 2024/825; applies from 27 September 2026): a high-sensitivity consumer-facing green claim appears to require stronger substantiation, clearer scope or safer wording ahead of the applicability date. Existing UCPD/national unfair-commercial-practices rules may already be relevant today.')
            break
    for f in social_findings or []:
        typ=(f.get('type','')+' '+f.get('issue','')+' '+f.get('claim','')).lower()
        if f.get('risk')=='High' and any(t in typ for t in ['forced labour','forced labor','modern slavery','product traceability','import controls','supplier traceability']):
            flags.append('Forced Labour Regulation readiness & substantiation flag (Regulation (EU) 2024/3015; core provisions apply from 14 December 2027): forced-labour, modern-slavery, traceability or product/supplier assurance wording should be escalated for legal/compliance review ahead of that date. This is a substantiation and readiness signal, not a finding that the Regulation has been breached.')
            break
    return flags

def build_company_action_plan(findings,sector,ext):
    actions=[{"priority":"Priority 1","title":"Create a social-claim register","action":"List all external social, labour, human-rights, diversity, customer and supplier claims and assign an internal owner."}]
    if any(f.get("risk")=="High" for f in findings): actions.append({"priority":"Priority 2","title":"Rewrite broad or absolute claims","action":"Replace generic wording such as ethical, responsible, fair, fully, all or for everyone with scoped, measurable and evidence-backed wording."})
    actions.append({"priority":"Priority 3","title":"Attach evidence to each claim","action":"For each claim, document the reporting period, scope, KPI, methodology, data source, limitations and approval owner."})
    if any(("supplier" in f.get("type","").lower() or "supply" in f.get("type","").lower()) for f in findings): actions.append({"priority":"Priority 4","title":"Strengthen supplier-claim substantiation","action":"Add supplier-tier coverage, audit methodology, corrective-action closure rates, grievance channels and remediation evidence."})
    if ext.get("enabled") and ext.get("results"): actions.append({"priority":"Priority 5","title":"Review external-source signals","action":"Check whether public-source signals contradict or qualify website claims and record how the company addresses them."})
    return actions[:6]

def build_engagement_questions(findings,ext):
    qs=[]
    for f in findings[:4]:
        t=f.get("type","").lower()
        if "supply" in t or "supplier" in t: qs.append("What percentage of suppliers and supplier tiers is covered by due diligence, and what corrective actions were closed during the reporting period?")
        elif "human" in t or "labour" in t or "labor" in t: qs.append("What salient human-rights risks were identified, and what grievance and remediation mechanisms are available to affected workers or communities?")
        elif "diversity" in t or "inclusion" in t: qs.append("Which workforce diversity, inclusion or pay-equity indicators support the claim, and what progress was made versus baseline?")
        elif "customer" in t or "accessibility" in t: qs.append("Which customer outcome, accessibility, complaint and remedy indicators support the claim?")
        else: qs.append("What evidence, methodology and reporting boundary support this claim, and what limitations should be disclosed?")
    if ext.get("enabled") and ext.get("results"): qs.append("How has management assessed and responded to the external public-source signals identified in this scan?")
    out=[]
    for q in qs:
        if q not in out: out.append(q)
    return out[:6]

def build_confidence(pages,ext,findings,crawl_log=None):
    pts=0; reasons=[]
    if len(pages)>=3: pts+=2; reasons.append("several company pages were reviewed")
    elif len(pages)>=1: pts+=1; reasons.append("at least the main company page was reviewed")
    ext_search_failed=bool(ext.get("search_failed"))
    if ext.get("enabled") and len(ext.get("results",[]))>=5: pts+=2; reasons.append("external public-source search returned several results")
    elif ext.get("enabled") and not ext_search_failed: pts+=1; reasons.append("external public-source search was active")
    elif ext_search_failed: reasons.append("external public-source search failed to run (provider error/quota, not a clean result)")
    else: reasons.append("external public-source search was not active")
    no_findings=not findings or is_placeholder_finding(findings[0].get("type",""))
    if not no_findings: pts+=1; reasons.append("claim-level signals were detected")

    # v56: fold crawl reliability into confidence instead of leaving it as a silent side-channel.
    # A scan that mostly failed or returned thin/blocked pages should not read the same as a
    # scan that genuinely reached the site and found little to flag.
    # A plain 404 on a speculative COMMON_PUBLIC_PATHS guess (e.g. trying /esg, /planet,
    # /responsible-sourcing on every candidate domain) just confirms that guessed path does
    # not exist on this particular site -- that is the expected outcome for most of those
    # guesses on most sites, not evidence of blocking or unreachability. Counting it the same
    # as a genuine 403/timeout inflates the failure ratio and triggers a misleading "blocked"
    # warning even on scans that reached the site fine via its real, linked pages.
    reliability_log=[e for e in (crawl_log or [])
                      if not (e.get("source")=='common_path' and not e.get("ok") and e.get("http_status")==404)]
    blocked=[e for e in reliability_log if not e.get("ok")]
    thin=[e for e in reliability_log if e.get("ok") and e.get("thin")]
    fallback_pages=[e for e in reliability_log if e.get("ok") and e.get("method")=='reader_fallback']
    attempted=len(reliability_log)
    reliability_warning=None
    if attempted:
        failure_ratio=len(blocked)/attempted
        if failure_ratio>0.25 or (len(pages)<3 and blocked):
            pts=max(0,pts-(2 if failure_ratio>=0.5 else 1))
            reliability_warning=(f"{len(blocked)} of {attempted} page fetches failed (e.g. HTTP 403/blocked or unreachable). "
                                  "A low risk score from this scan may reflect limited access to the site's content, "
                                  "not necessarily a genuine absence of risky claims.")
        elif thin:
            pts=max(0,pts-1)
            reliability_warning=(f"{len(thin)} of {attempted} fetched page(s) returned unusually little text, which can happen "
                                  "with JavaScript-rendered pages or soft bot-blocks. A low risk score from this scan may reflect "
                                  "limited access to the site's content, not necessarily a genuine absence of risky claims.")
        elif fallback_pages:
            pts=max(0,pts-1)
            reliability_warning=(f"{len(fallback_pages)} reviewed page(s) required a public text-extraction fallback. "
                                  "A low risk score from this scan may reflect limited access to the site's content, "
                                  "not necessarily a genuine absence of risky claims.")
        elif len(pages)<3:
            pts=max(0,pts-1)
            reliability_warning=(f"Only {len(pages)} relevant company page(s) could be reviewed. "
                                  "A low risk score from this scan may reflect limited access to the site's content, "
                                  "not necessarily a genuine absence of risky claims.")
    if ext_search_failed:
        pts=max(0,pts-1)
        reliability_warning=("External public-source search failed to run (every provider request errored, e.g. a rate "
                              "limit or usage quota) rather than returning zero results. Any 'no external negative "
                              "signal' conclusion in this scan is not confirmation of a clean external record -- the "
                              "search simply did not execute. " + (reliability_warning or ""))
    if no_findings and (blocked or thin):
        reliability_warning=reliability_warning or ("No claims were detected, and part of the crawl did not return usable content. "
                                                      "This scan result should be treated as inconclusive rather than 'low risk'.")
    # v57p: distinguish "Insufficient coverage" from an ordinary "Low" confidence result. "Low"
    # can also mean a small, genuinely reachable site with little to say; "Insufficient coverage"
    # specifically flags that most of the crawl failed outright, so there usually isn't enough
    # material to draw ANY conclusion from, favourable or not.
    if attempted and len(blocked)/attempted >= 0.75 and len(pages) <= 1:
        level_str="Insufficient coverage"
    else:
        level_str="High" if pts>=5 else "Medium" if pts>=3 else "Low"
    result={"level":level_str,"reasons":reasons,"attempted":attempted,"blocked":len(blocked)}
    if reliability_warning:
        result["reliability_warning"]=reliability_warning
    return result

def split_scores(findings,sector,context,external_modifier,score_components=None):
    if score_components:
        return {k:score_components[k] for k in ["claim_wording_risk","substantiation_risk","external_context_risk","sector_baseline_risk"] if k in score_components}
    claim=max((f.get("claim_score",0) for f in findings), default=0)
    return {"claim_wording_risk":min(100,round(claim*.75)),"substantiation_risk":50,"external_context_risk":min(100,round((external_modifier or 0)*4+{"Low":5,"Medium":25,"High":50,"Very high":70}.get(context.get("level","Low"),5))),"sector_baseline_risk":{"Low":10,"Medium":35,"High":60}.get(sector.get("level","Medium"),35)}

def concise_standards_lens():
    return [
        {"name":"CSRD / ESRS", "use":"Are social claims linked to stakeholder impacts, policies, actions, targets and metrics?"},
        {"name":"CSDDD / OECD / UNGPs", "use":"Are human-rights and value-chain claims supported by due diligence, prevention, mitigation and remedy?"},
        {"name":"EU Forced Labour Regulation 2024/3015", "use":"For product, supplier, import/export or modern-slavery claims: is there evidence of forced-labour risk assessment, traceability, remediation and withdrawal/customs response readiness?"},
        {"name":"ILO / UNGC / GRI", "use":"Are labour, inclusion and responsible-business claims specific, balanced and evidence-based?"}
    ]

def strict_external_context_risk(external_research, company_name=""):
    """
    V17: external context risk is only very high where there are serious AND repeated
    public-source allegations focused on the concrete company.
    """
    results = external_research.get("results", []) if external_research else []
    if not results:
        return {"score":0, "level":"Low", "note":"No usable external public-source signals were found."}

    company_key = (company_name or "").lower().split("/")[0].strip()
    serious_terms = ["forced labour","forced labor","eu forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","human rights","lawsuit","court","regulator","regulatory","discrimination","strike","union","living wage","complaint","oecd","ncp"]
    medium_terms = ["supplier","workers","supply chain","accessibility","grievance","ngo","audit","wage","safety","customer protection"]

    serious_hits = 0
    medium_hits = 0
    company_hits = 0
    credible_sources = 0
    urls = set()

    for r in results:
        txt = (r.get("title","") + " " + r.get("content","") + " " + r.get("url","")).lower()
        if r.get("url"):
            urls.add(r.get("url"))
        if company_key and company_key in txt:
            company_hits += 1
        if any(t in txt for t in serious_terms):
            serious_hits += 1
        if any(t in txt for t in medium_terms):
            medium_hits += 1
        if r.get("credibility") in ["High","Medium-high"] or any(x in txt for x in ["oecd","europa.eu",".gov","reuters","bbc","ft.com","amnesty","human rights watch"]):
            credible_sources += 1

    repeated = len(urls) >= 3 and (serious_hits + medium_hits) >= 3
    serious_and_repeated = serious_hits >= 3 and repeated and (company_hits >= 2 or not company_key) and credible_sources >= 1

    if serious_and_repeated:
        return {"score":85, "level":"Very high", "note":"Serious and repeated external allegations appear focused on the company and are supported by multiple public sources."}
    if serious_hits >= 2 and repeated:
        return {"score":65, "level":"High", "note":"Several serious external signals were found, but they should be verified before being treated as established facts."}
    if serious_hits >= 1 or medium_hits >= 2:
        return {"score":40, "level":"Medium", "note":"Some external signals are relevant to the company or claim themes, but the pattern is not severe or repeated enough for a very high context score."}
    return {"score":15, "level":"Low", "note":"External search returned limited or weakly relevant context signals."}

def integrated_score_view(overall_score, split_scores, external_context):
    return {
        "overall": overall_score,
        "claim_wording_risk": split_scores.get("claim_wording_risk",0),
        "substantiation_risk": split_scores.get("substantiation_risk",0),
        "external_context_risk": split_scores.get("external_context_risk", external_context.get("score",0)),
        "sector_baseline_risk": split_scores.get("sector_baseline_risk",0),
        "formula": "Overall score = 50% claim wording risk + 22% substantiation/evidence-gap risk + 20% external contradictory-context risk + 8% sector sensitivity.",
        "weights": "High social-washing risk requires a sensitive or broad social claim, insufficient substantiation and relevant external contradiction. Sector sensitivity is a modifier only."
    }

def merge_claim_sections(findings, company=None, sector=None):
    company = company or {"company":"the company"}
    sector = sector or {"level":"Medium"}
    rows = []
    for f in findings:
        rows.append({
            "claim_text": f.get("claim",""),
            "claim_type": f.get("type",""),
            "risk_level": f.get("risk",""),
            "claim_score": f.get("claim_score",0),
            "standards": f.get("standards", []),
            "analysis": (f.get("issue","") + " " + f.get("action","")).strip(),
            "evidence_needed": evidence_checklist(f),
            "suggested_rewrite": f.get("rewrite","")
        })
    return rows


NEGATIVE_SIGNAL_TERMS = [
    "greenwashing","social washing","misleading","accused","accusation","allegation","criticised","criticized","criticism",
    "complaint","lawsuit","court","investigation","fine","penalty","sanction","regulator","authority","watchdog",
    "ngo","union","strike","protest","boycott","violation","breach","forced labour","forced labor","child labour",
    "child labor","modern slavery","human rights abuse","labour rights","labor rights","unsafe","discrimination",
    "worker rights","supply chain controversy","class action","settlement","ban","prohibited"
]
POSITIVE_NOISE_TERMS = [
    "award","awarded","wins","recognised","recognized","partnership","partnered","sponsor","donation",
    "new product","launches","opens","expands","growth","profit","revenue","appointment","campaign",
    "success story","best practice","ranking","ranked","certificate","certified","collaboration","initiative",
    "how to","guide","webinar","event","conference","training","job","vacancy"
]
OWNED_OR_NEUTRAL_DOC_TERMS = [
    "sustainability report","sustainability statement","annual report","integrated report","esg report","non-financial report",
    "corporate responsibility report","impact report","human rights policy","human rights statement","supplier code",
    "supplier policy","supplier standards","code of conduct","modern slavery statement","due diligence statement",
    "policy","policies","our sustainability","our responsibility","our human rights","our suppliers",
    "press release","newsroom","media release","corporate news","investor relations","results presentation",
    "jaarverslag","duurzaamheidsverslag","rapport annuel","rapport de durabilité"
]
def _external_signal_text(result):
    return (result.get("title","")+" "+result.get("content","")+" "+result.get("url","")).lower()

def negative_compact_sources(results, limit=5):
    filtered = [r for r in results if is_negative_external_source(r)]
    if "compact_sources" in globals():
        return compact_sources(filtered, limit)
    return filtered[:limit]
def company_specific_summary(company, sector, context, findings, external_research, score):
    company_name = company.get("company", "The company")
    claim_types = [f.get("type","") for f in findings if f.get("type")]
    quoted = [f.get("claim","") for f in findings if f.get("claim")]
    top_claim = quoted[0] if quoted else ""
    negative_count = len([r for r in (external_research.get("results", []) if external_research else []) if is_negative_external_source(r)])
    high_claims = [f for f in findings if f.get("risk") == "High"]
    if findings and is_placeholder_finding(findings[0].get("type","")):
        claim_sentence = "The scan did not identify a strong high-risk social-washing claim in the reviewed company pages."
    elif high_claims:
        claim_sentence = "The main risk comes from high-sensitivity wording around " + ", ".join(claim_types[:2]) + "."
    else:
        claim_sentence = "The main risk comes from moderate wording around " + ", ".join(claim_types[:2]) + "."
    if top_claim:
        claim_sentence += " The most relevant company wording reviewed was: “" + top_claim + "”."
    if negative_count:
        ext_sentence = f"The external-source layer retained {negative_count} negative or risk-relevant public-source signal(s), which should be verified before conclusions are drawn."
    else:
        ext_sentence = "No clearly negative external public-source signal was retained for the concise source section."
    return f"{company_name} receives a social-washing risk score of {score}/100. {claim_sentence} Sector context is {sector.get('level','Medium').lower()} for {company.get('sector','the identified sector')}. {ext_sentence} The priority is to ensure that social, labour, human-rights, customer or supplier claims are specific, scoped, evidenced and not contradicted by relevant public information."
def specific_claim_analysis(finding, company, sector):
    claim_type = finding.get("type","claim")
    claim = finding.get("claim","")
    issue = finding.get("issue","")
    company_name = company.get("company","The company")
    sector_level = sector.get("level","Medium")
    if finding.get("risk") == "High":
        tone = "This wording may create a strong expectation that the company has effective controls and evidence in place."
    elif finding.get("risk") == "Medium":
        tone = "This wording is not necessarily problematic, but it needs clearer scope and evidence."
    else:
        tone = "This wording appears lower risk, but should still be checked for substantiation."
    return f"For {company_name}, this {claim_type.lower()} is relevant because the reviewed wording says: “{claim}”. {tone} {issue} Given the {sector_level.lower()} sector exposure, the claim should be linked to concrete scope, metrics, reporting period, limitations and accountable governance."
def structured_why_score(company, sector, context, findings, external_context, split_scores, score_components=None):
    ev_notes=(score_components or {}).get("evidence_notes", [])
    return {
        "claim_wording": f"Claim wording risk is {split_scores.get('claim_wording_risk',0)}/100. This reflects the breadth, sensitivity and absoluteness of the social claims detected on the reviewed pages.",
        "substantiation": f"Substantiation risk is {split_scores.get('substantiation_risk',0)}/100. " + (" ".join(ev_notes) if ev_notes else "This reflects whether website evidence supports the claim with scope, metrics, reporting period, limitations and remedy."),
        "external_context": f"External contradictory-context risk is {split_scores.get('external_context_risk',0)}/100. {external_context.get('note','Only negative or risk-relevant public-source signals are retained in the concise source section.')}",
        "sector_context": f"Sector baseline risk is {split_scores.get('sector_baseline_risk',0)}/100. The sector assessment is {sector.get('level','Medium')} because {sector.get('risks','sector exposure was identified from the company profile and page content')}.",
        "interpretation": "The result is a screening signal for social-washing assessment. It is not a legal finding and should be verified manually before use in external communications."
    }

def company_terms_for_filter(company_name):
    raw = (company_name or "").lower()
    parts = []
    for sep in ["/", "|", ",", "-", " "]:
        if sep in raw:
            parts.extend([p.strip() for p in raw.split(sep) if len(p.strip()) >= 3])
    if len(raw) >= 3:
        parts.append(raw)
    return list(dict.fromkeys(parts))


def _root_domain(url_or_host):
    host=(urlparse(url_or_host).hostname or url_or_host or '').lower().replace('www.','').strip()
    if not host: return ''
    parts=[x for x in host.split('.') if x]
    if len(parts) >= 3 and parts[-2] in {'co','com','org','net','ac','gov'} and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return host

def company_owned_roots(reviewed_pages=None):
    roots=set()
    for u in reviewed_pages or []:
        root=_root_domain(u)
        if root:
            roots.add(root)
    return roots



def reader_friendly_summary(company, sector, findings, external_research, score, score_components=None):
    name = company.get("company", "The company")
    sector_name = company.get("sector", "the identified sector")
    claim_findings = [f for f in findings if not is_placeholder_finding(f.get("type",""))]
    first = claim_findings[0] if claim_findings else None
    targeted = targeted_negative_sources(external_research.get("results", []) if external_research else [], name, 10)
    comps=score_components or {}
    conclusion=washing_conclusion(score, findings, comps.get("substantiation_risk",50), comps.get("external_context_risk",0))
    if first:
        claim_part = "The most relevant claim area is " + first.get("type","social claims").lower() + "."
        quote = " The key company wording reviewed was: “" + first.get("claim","") + "”." if first.get("claim") else ""
    else:
        claim_part = "The scan did not identify a clear high-risk social-washing claim in the reviewed website text."
        quote = ""
    source_part = "No targeted negative public-source signal was retained."
    if targeted:
        source_part = f"{len(targeted)} targeted negative public-source signal(s) were retained for review."
    return (
        f"{name} receives a social-washing assessment score of {score}/100: {conclusion}. "
        f"{claim_part}{quote} The substantiation-risk component is {comps.get('substantiation_risk','n/a')}/100. "
        f"The sector context is {sector.get('level','Medium').lower()} for {sector_name}. "
        f"{source_part} The priority is to check whether the claim is specific, evidenced, scoped and consistent with public information."
    )




# -----------------------------
# V27 GREEN + SOCIAL CLAIMS EXTENSION
# -----------------------------
# Green-claims module based on Directive (EU) 2024/825 (EmpCo), which amends the UCPD.
# The directive is primarily a B2C/commercial-communication consumer-protection framework.
# This scanner therefore distinguishes consumer-facing pages from investor/internal reports.



EMPCO_LENS=[
 {'name':'EmpCo / Directive (EU) 2024/825 ("Empowering Consumers for the Green Transition" Directive)','use':'Amends the Unfair Commercial Practices Directive (2005/29/EC) and the Consumer Rights Directive (2011/83/EU). Member States must transpose by 27 March 2026; the rules apply from 27 September 2026. Covers both green AND social claims: Article 6(1)(b), as amended, brings "environmental or social characteristics" of a product or trader within the general misleading-claims test (Recital 3 names wages, safety, human rights, equal treatment, gender equality, inclusion and diversity as social characteristics in scope) -- this lens is therefore not limited to green claims.'},
 {'name':'EU Forced Labour Regulation / Regulation (EU) 2024/3015 (core provisions apply from 14 December 2027)','use':'Main forced-labour and supply-chain assurance lens for forced-labour/traceability wording. Flags wording that may imply products, suppliers or value chains are free from forced labour, or that traceability, due diligence or import/export controls provide assurance beyond what is evidenced. It is a market-prohibition and customs-enforcement regime, not a claims law, and Art. 1(3) confirms it creates no new due-diligence obligation of its own -- readiness matters ahead of 2027, not an existing statutory breach today.'},
 {'name':'UCPD environmental-claim definition','use':'Checks whether text, images, symbols, labels, brand names, trade names or presentation imply positive, zero, reduced, comparative or improved environmental impact of a product, brand or trader.'},
 {'name':'Blacklisted-practices lens (Annex I)','use':'Flags high-sensitivity indicators that Annex I treats as unfair in all circumstances: generic environmental claims without recognised excellent environmental performance (4a), claiming an entire product/business benefit when only one aspect or activity is meant (4b), product-level claims of neutral/reduced/positive climate impact based on offsetting (4c), sustainability labels not based on a qualifying certification scheme or not established by public authorities (2a), and presenting a legal requirement as a distinctive feature (10a).'},
 {'name':'Same-medium specification check','use':'Checks whether broad wording is specified clearly and prominently on the same page, advertisement, packaging text or product interface.'},
 {'name':'Climate / offsetting claims','use':'Separates actual emission reductions from offsetting or compensation and treats product-level neutrality wording based on offsets as a high-priority risk area (Annex I, point 4c).'},
 {'name':'Sustainability labels and visual claims','use':'Checks icons, badges, symbols and labels against independent certification, public-authority schemes, transparent criteria and validity (Annex I, point 2a).'},
 {'name':'Future environmental performance','use':'Article 6(2)(d), assessed case-by-case (not an automatic Annex I ban): future claims should be supported by clear, objective, publicly verifiable commitments, implementation plans, milestones, resources, governance and independent third-party review.'},
 {'name':'Comparative environmental or social claims','use':'Recital 6 / Article 7(7): comparisons should disclose the comparison method, products/suppliers compared, data date, scope and update mechanism; comparison services have an explicit information duty under the new Article 7(7).'},
 {'name':'Consumer-facing communications','use':'EmpCo has strongest relevance for B2C/commercial communications; investor and internal documents remain relevant as evidence or consistency sources but are not treated the same as consumer marketing material.'},
 {'name':'Known scope gap in this scan','use':'Article 6(2)(e) also prohibits advertising a consumer benefit that is irrelevant and unrelated to any actual feature of the product or business (Recital 5 examples: a bottled water advertised as gluten-free, paper sheets advertised as not containing plastic). This requires judging relevance to the specific product, which this automated scan does not attempt -- irrelevant-benefit claims are not flagged and should be checked manually.'}
]


CONSUMER_TERMS=['shop','buy','product','products','service','services','customers','consumer','pricing','offer','promotion','campaign','brochure','leaflet','folder','advertising','marketing','homepage','store','brand','claims','landing page','commercial']
INVESTOR_TERMS=['annual report','sustainability report','integrated report','esg report','investor','shareholder','csrd','esrs','financial report','non-financial statement','taxonomy','management report','remuneration report','annualreview']
INTERNAL_TERMS=['policy','code of conduct','supplier code','internal','procedure','manual','guideline','governance','standard','due diligence statement','modern slavery statement']

def _term_hits(blob, terms):
    return sum(1 for t in terms if t in blob)

def classify_page_audience(url, text=''):
    """Classify an individual checked URL/document into the channel used in the analysis."""
    blob=((url or '')+' '+(text or '')[:6000]).lower()
    consumer=_term_hits(blob, CONSUMER_TERMS)
    investor=_term_hits(blob, INVESTOR_TERMS)
    internal=_term_hits(blob, INTERNAL_TERMS)
    if investor>=2 and investor>=consumer:
        return {
            'audience':'Investor reporting',
            'group':'investor',
            'empco_relevance':'Indirect / evidence source',
            'interpretation':'Used mainly as substantiation evidence for claims; not treated like consumer advertising unless the same wording is reused in market-facing material.'
        }
    if internal>=2 and internal>consumer:
        return {
            'audience':'Policy / internal governance document',
            'group':'internal',
            'empco_relevance':'Indirect / governance evidence',
            'interpretation':'Used as internal-control or due-diligence evidence. The scan does not treat internal governance language as consumer-facing marketing.'
        }
    if consumer>=2 or any(x in blob for x in ['product','shop','brochure','campaign','advertising','customer','consumer','homepage']):
        return {
            'audience':'Client-facing / consumer-facing communication',
            'group':'client_facing',
            'empco_relevance':'Direct / high',
            'interpretation':'Assessed as external market-facing wording. EmpCo-style scrutiny is directly relevant for green claims and the wording burden is higher.'
        }
    return {
        'audience':'Mixed or unclear external communication',
        'group':'mixed',
        'empco_relevance':'Medium',
        'interpretation':'May combine corporate, commercial and investor/reporting language. Treat product, homepage or brochure wording as higher-risk than report-style background text.'
    }

def extract_page_segments(full_text, pages):
    """Return approximate text segment per crawled page so audience and claim-source links can be
    more precise.
    v57v: the crawler can emit three different markers when assembling the combined text --
    "PAGE: url" for a regular sub-page, "REPORT (PDF): url" for a PDF report, and
    "RELATED COMPANY SITE: domain" for a related/group domain's own crawl (itself containing
    further nested "PAGE: url" markers, since crawl_with_related_sites() appends that whole
    domain's own crawl() output, unmodified, after this label).
    v57w: the v57v version recognised the RELATED COMPANY SITE marker but did not re-split its
    body for the nested PAGE:/REPORT (PDF): markers inside it -- so an entire related domain's
    worth of distinct pages (e.g. every sustainability sub-page of a group's main corporate
    site) collapsed into one segment tagged with just the bare related-domain label. Claims
    actually found on one of those inner pages then failed exact-text source-matching (their
    text lived deep inside one merged blob, not at a page-level segment) and fell through to the
    token-overlap fallback, which could land on an unrelated primary-domain page purely by
    incidental word overlap -- exactly the "every claim attributed to the same wrong article"
    pattern this was meant to fix. Recurse into the RELATED COMPANY SITE body so its own pages
    become first-class segments too."""
    pages=pages or []
    if not pages:
        return []
    text=full_text or ''
    # v87: the actual marker crawl_with_related_sites() writes is "RELATED OFFICIAL COMPANY
    # SITE: " (see the append call there) -- this split regex and the comparison below were
    # still looking for the shorter "RELATED COMPANY SITE: " with no "OFFICIAL", so the branch
    # below was DEAD CODE: it never matched, and a related/group domain's entire crawl output
    # silently became part of whichever primary-domain page happened to precede it in the text,
    # instead of getting its own page-level segments. This defeated claim-source attribution,
    # _v86_claim_local_text()'s evidence-locality fix and infer_sector()'s homepage-preference
    # fix for every claim actually sourced from a related/group domain page.
    parts=re.split(r'\n\n(PAGE|REPORT \(PDF\)|RELATED OFFICIAL COMPANY SITE): ', text)
    segments=[{'url':pages[0] if pages else '', 'text':parts[0]}]
    i=1
    while i < len(parts)-1:
        marker_type=parts[i]
        rest=parts[i+1]
        line, _, body = rest.partition('\n')
        label=line.strip()
        if marker_type == 'RELATED OFFICIAL COMPANY SITE':
            nested=re.split(r'\n\n(PAGE|REPORT \(PDF\)): ', body)
            if label:
                segments.append({'url':label, 'text':nested[0]})
            j=1
            while j < len(nested)-1:
                nrest=nested[j+1]
                nline, _, nbody = nrest.partition('\n')
                nurl=nline.strip()
                if nurl:
                    segments.append({'url':nurl, 'text':nbody})
                j+=2
        elif label:
            segments.append({'url':label, 'text':body})
        i+=2
    # Ensure every page has a segment, even when parsing failed.
    known={x['url'] for x in segments}
    for p in pages:
        if p not in known:
            segments.append({'url':p, 'text':''})
    return segments

def classify_document_audience(url, text, pages=None):
    segments=extract_page_segments(text, pages or [url])
    if not segments:
        segments=[{'url':url,'text':text or ''}]
    classifications=[classify_page_audience(x.get('url'), x.get('text','')) for x in segments]
    counts={}
    for c in classifications:
        counts[c['group']]=counts.get(c['group'],0)+1
    if counts.get('client_facing',0)>0 and counts.get('investor',0)==0 and counts.get('internal',0)==0:
        aud='Client-facing / consumer-facing communication'; emp='Direct / high'; group='client_facing'
        note='The reviewed material is mainly market-facing. Green claims should be assessed with stronger EmpCo-style consumer-communication controls.'
    elif counts.get('investor',0)>0 and counts.get('client_facing',0)==0:
        aud='Investor reporting'; emp='Indirect / evidence source'; group='investor'
        note='The reviewed material is mainly annual reports, sustainability reports, ESG reports or investor reporting. Treat it primarily as evidence or context, not as consumer advertising, unless the same claims are reused externally.'
    elif counts.get('internal',0)>0 and counts.get('client_facing',0)==0:
        aud='Policy / internal governance material'; emp='Indirect / governance evidence'; group='internal'
        note='The reviewed material appears to be policy or governance material. It is useful as substantiation evidence, but wording risk is lower than in consumer-facing material.'
    else:
        aud='Mixed channel set'; emp='Mixed'; group='mixed'
        note='The scan includes more than one communication channel. The analysis separates client-facing communication from investor reporting and policy/internal governance material.'
    return {'audience':aud,'empco_relevance':emp,'note':note,'channel_counts':counts,'group':group}


def page_name_from_url(u):
    try:
        parsed=urlparse(u)
        path=(parsed.path or '').strip('/')
        if not path:
            return parsed.netloc or u
        name=path.split('/')[-1] or path.split('/')[-2]
        name=name.replace('-', ' ').replace('_',' ')
        return name[:90] or u
    except Exception:
        return u

def document_type_from_url(u):
    low=(u or '').lower()
    if any(t in low for t in ['annual-report','annual_report','integrated-report','sustainability-report','esg-report','investor','csrd','report']):
        return 'Investor report'
    if any(t in low for t in ['policy','code-of-conduct','supplier-code','procedure','manual','governance','modern-slavery-statement']):
        return 'Policy / internal governance document'
    if any(t in low for t in ['product','shop','buy','brochure','folder','campaign','customer','consumer','store']):
        return 'Client-facing / consumer-facing communication'
    if low.endswith('.pdf'):
        return 'PDF document / manual review recommended'
    return 'Website page'

def build_documents_checked(pages, audience, full_text=None):
    segments=extract_page_segments(full_text or '', pages or [])
    seg_by_url={x['url']:x.get('text','') for x in segments}
    seen=set(); out=[]
    for p in pages or []:
        if not p or p in seen: continue
        seen.add(p)
        cls=classify_page_audience(p, seg_by_url.get(p,''))
        out.append({
            'name': page_name_from_url(p),
            'url': p,
            'document_type': document_type_from_url(p),
            'audience_assessment': cls.get('audience','Unknown'),
            'audience_group': cls.get('group','mixed'),
            'empco_relevance': cls.get('empco_relevance','Unknown'),
            'interpretation': cls.get('interpretation','')
        })
    return out


def build_scan_inventory(pages, documents_checked=None, crawl_log=None, full_text=None):
    """Build a transparent source register with retrieval and analysis status."""
    pages=list(pages or [])
    documents_checked=list(documents_checked or [])
    crawl_log=list(crawl_log or [])

    def canon(value):
        try: return _canonical_url(str(value or ''))
        except Exception: return str(value or '').strip()

    segments=extract_page_segments(full_text or '', pages) if full_text is not None else []
    analysed_by_url={canon(seg.get('url')):len((seg.get('text') or '').strip()) for seg in segments if seg.get('url')}
    docs_by_url={canon(d.get('url')):d for d in documents_checked if isinstance(d,dict) and d.get('url')}
    success_by_url={}
    for entry in crawl_log:
        if isinstance(entry,dict) and entry.get('ok') and entry.get('url'):
            success_by_url[canon(entry.get('url'))]=entry

    def classify_status(extracted, analysed, method):
        extracted=max(0,int(extracted or 0)); analysed=max(0,int(analysed or 0))
        if extracted and analysed==0:
            return 'Retrieved but not analysed due to budget','The source was retrieved, but its text did not enter the final analysis text.'
        # v73: a short source that was fully read (analysed ~= extracted) is not "limited" --
        # only genuinely thin sources (very little text found at all) or sources where most of
        # the extracted text was cut before analysis should be flagged this way.
        if str(method or '').lower()=='direct_thin' or extracted<150:
            return 'Limited text extracted','Only a limited amount of usable text was available; findings may be incomplete.'
        if extracted>1200 and analysed < max(500,int(extracted*0.55)):
            return 'Retrieved and partially analysed','Only part of the extracted text entered the bounded analysis text.'
        return 'Retrieved and analysed','Usable source text entered the claim analysis.'

    reviewed=[]; seen=set()
    for value in pages:
        url=str(value or '').strip()
        if not url: continue
        key=canon(url)
        if key in seen: continue
        seen.add(key)
        doc=docs_by_url.get(key,{})
        log=success_by_url.get(key,{})
        kind=(log.get('content_kind') or '').lower()
        low=url.lower().split('?',1)[0]
        doc_type_low=str(doc.get('document_type','')).lower()
        is_document=(kind=='pdf' or low.endswith('.pdf') or ('uploaded' in doc_type_low and 'document' in doc_type_low))
        parsed=urlparse(url) if url.startswith(('http://','https://')) else None
        domain=((parsed.hostname or '').replace('www.','') if parsed else '')
        extracted=int(log.get('chars') or 0)
        analysed=int(analysed_by_url.get(key, len(full_text or '') if len(pages)==1 and full_text else 0))
        status,status_note=classify_status(extracted or analysed,analysed,log.get('method'))
        reviewed.append({
            'name':doc.get('name') or page_name_from_url(url),'url':url,
            'source_type':'Document / PDF' if is_document else 'Website page','domain':domain,
            'document_type':doc.get('document_type') or ('PDF document' if is_document else 'Website page'),
            'audience_assessment':doc.get('audience_assessment') or 'Not assessed','empco_relevance':doc.get('empco_relevance') or 'Not assessed',
            'fetch_method':log.get('method') or ('uploaded' if not url.startswith(('http://','https://')) else 'direct'),
            'discovery_source':log.get('source') or ('uploaded' if not url.startswith(('http://','https://')) else 'reviewed'),
            'characters_extracted':extracted or analysed,'characters_analysed':analysed,
            'analysis_status':status,'analysis_note':status_note,'claim_signal_count':0,'claim_dimensions':[],
            'used_fallback':bool(log.get('method')=='reader_fallback')})

    for doc in documents_checked:
        if not isinstance(doc,dict): continue
        url=str(doc.get('url') or '').strip(); key=canon(url)
        if not url or key in seen: continue
        seen.add(key)
        analysed=len(full_text or '') if len(pages)<=1 else 0
        status,status_note=classify_status(analysed,analysed,'uploaded')
        reviewed.append({'name':doc.get('name') or page_name_from_url(url),'url':url,'source_type':'Document / PDF','domain':'',
                         'document_type':doc.get('document_type') or 'Document','audience_assessment':doc.get('audience_assessment') or 'Not assessed',
                         'empco_relevance':doc.get('empco_relevance') or 'Not assessed','fetch_method':'uploaded','discovery_source':'uploaded',
                         'characters_extracted':analysed,'characters_analysed':analysed,'analysis_status':status,'analysis_note':status_note,
                         'claim_signal_count':0,'claim_dimensions':[],'used_fallback':False})

    failed=[]; failed_seen=set()
    for entry in crawl_log:
        if not isinstance(entry,dict) or entry.get('ok') or not entry.get('url'): continue
        key=canon(entry.get('url'))
        if key in failed_seen: continue
        failed_seen.add(key)
        failed.append({'url':entry.get('url'),'name':page_name_from_url(entry.get('url')),'http_status':entry.get('http_status'),
                       'error':entry.get('error') or 'The page could not be accessed.','discovery_source':entry.get('source') or 'discovered'})

    page_items=[x for x in reviewed if x.get('source_type')=='Website page']
    document_items=[x for x in reviewed if x.get('source_type')!='Website page']
    domains=sorted({x.get('domain') for x in reviewed if x.get('domain')})
    status_counts={}
    for item in reviewed: status_counts[item.get('analysis_status','Unknown')]=status_counts.get(item.get('analysis_status','Unknown'),0)+1
    return {'summary':{'reviewed_total':len(reviewed),'website_pages_reviewed':len(page_items),'documents_reviewed':len(document_items),
                       'domains_reviewed':len(domains),'fetch_attempts':len(crawl_log),'fetch_failures':len(failed),
                       'fallback_pages':len([x for x in reviewed if x.get('used_fallback')]),
                       'fully_analysed':status_counts.get('Retrieved and analysed',0),
                       'partially_analysed':status_counts.get('Retrieved and partially analysed',0),
                       'limited_text':status_counts.get('Limited text extracted',0),
                       'retrieved_not_analysed':status_counts.get('Retrieved but not analysed due to budget',0)},
            'website_pages':page_items,'documents':document_items,'failed_fetches':failed,'domains':domains,
            'note':''}


def attach_claim_counts_to_inventory(inventory, claims):
    if not isinstance(inventory,dict): return inventory
    items=list(inventory.get('website_pages') or [])+list(inventory.get('documents') or [])
    for item in items:
        item['claim_signal_count']=0; item['claim_dimensions']=[]
    for claim in claims or []:
        # The synthetic "no claim retained" placeholder row (present whenever a document/page
        # genuinely had no material claim) was being counted the same as a real claim here,
        # so a page/document with zero actual findings could still show "1 claim signal" in
        # the coverage table -- e.g. a document with only a green claim also wrongly showed a
        # Social claim signal, purely from the social-side placeholder.
        if is_placeholder_finding(claim.get('claim_type') or claim.get('type') or ''):
            continue
        source=str(claim.get('source_url') or claim.get('source') or claim.get('source_label') or '').strip()
        if not source: continue
        try: skey=_canonical_url(source)
        except Exception: skey=source
        for item in items:
            try: ikey=_canonical_url(str(item.get('url') or ''))
            except Exception: ikey=str(item.get('url') or '')
            if skey==ikey or source==item.get('name'):
                item['claim_signal_count']=int(item.get('claim_signal_count') or 0)+1
                dim=str(claim.get('dimension') or ('green' if 'environment' in str(claim.get('claim_type','')).lower() else 'social')).title()
                if dim and dim not in item['claim_dimensions']: item['claim_dimensions'].append(dim)
                break
    return inventory

def build_channel_analysis(documents):
    docs=documents or []
    def pick(group): return [d for d in docs if d.get('audience_group')==group]
    client=pick('client_facing'); investor=pick('investor'); internal=pick('internal'); mixed=pick('mixed')
    def short(dlist): return [{'name':d.get('name'), 'url':d.get('url'), 'type':d.get('document_type')} for d in dlist[:8]]
    return {
        'client_facing':{
            'count':len(client), 'documents':short(client),
            'analysis_lens':'Higher wording and substantiation burden. For green claims, EmpCo-style consumer-protection scrutiny is directly relevant; broad, generic, comparative, label, climate-neutrality or future-performance wording should be tightly scoped and evidenced.'
        },
        'investor_stakeholder':{
            'count':len(investor), 'documents':short(investor),
            'analysis_lens':'Used mainly as substantiation and consistency evidence. Investor or sustainability reports can support claims, but report-style disclosure should not be scored as consumer advertising unless reused in market-facing channels.'
        },
        'policy_internal':{
            'count':len(internal), 'documents':short(internal),
            'analysis_lens':'Used as governance and due-diligence evidence. Internal policies, codes and procedures help substantiate social and forced-labour claims but are not in themselves client-facing promotional claims.'
        },
        'mixed_unclear':{
            'count':len(mixed), 'documents':short(mixed),
            'analysis_lens':'Manual channel review recommended. Where a page combines marketing and reporting language, apply stricter controls to statements that a customer or end-user is likely to see before purchase or engagement.'
        }
    }

def assign_claim_sources(claims, page_segments, documents):
    docs_by_url={d.get('url'):d for d in documents or []}
    for c in claims:
        txt=(c.get('claim_text') or '').strip().lower()
        best=None
        if txt and page_segments:
            words=txt.split()
            # v57n: the stored excerpt may have been lightly reformatted since it was extracted
            # (context sentence prepended when it looked like a fragment, internal processing
            # labels stripped, whitespace/newline-to-period normalisation) -- so it often no
            # longer appears as one exact long substring of the raw crawled page text. Try
            # several candidate windows (different lengths, and a mid-excerpt window in case a
            # prefix was added) before giving up on an exact match.
            candidates=[]
            for n in (10,7,5):
                if len(words)>=n:
                    candidates.append(' '.join(words[:n]))
            if len(words)>=14:
                mid=len(words)//3
                candidates.append(' '.join(words[mid:mid+8]))
            for probe in candidates:
                for seg in page_segments:
                    hay=(seg.get('text') or '').lower()
                    if probe and probe in hay:
                        best=seg.get('url'); break
                if best: break
            if not best:
                # No exact-substring match anywhere. Previously this silently defaulted to
                # page_segments[0] -- i.e. whichever page happened to be fetched/listed first --
                # which is worse than admitting the source page could not be confidently
                # identified: it actively mis-attributes claims to an unrelated page. Fall back
                # to scoring pages by how many distinctive words from the claim they contain, and
                # only trust that guess if the overlap is meaningful.
                sig_words=[w for w in words if len(w)>4][:25]
                if sig_words:
                    best_score=0; best_guess=None
                    for seg in page_segments:
                        hay=(seg.get('text') or '').lower()
                        score=sum(1 for w in sig_words if w in hay)
                        if score>best_score:
                            best_score=score; best_guess=seg.get('url')
                    if best_guess and best_score >= max(3, len(sig_words)//4):
                        best=best_guess
        if best:
            c['source_url']=best
            c['source_label']=page_name_from_url(best)
            d=docs_by_url.get(best,{})
            c['audience_group']=d.get('audience_group','mixed')
            c['audience_lens']=d.get('audience_assessment','Mixed or unclear')
            c['source_interpretation']=d.get('interpretation','')
        else:
            # v57n: be explicit rather than guessing wrong -- an unclear source is more honest
            # and more useful to a reviewer than a confidently wrong one.
            c['source_url']=''
            c['source_label']='Reviewed material (exact source page could not be confidently matched)'
    return claims


def assign_sources_to_findings(findings, page_segments, documents):
    """Attach page/document source details directly to UI findings.
    This keeps the claim-signal table traceable: source page/doc/link is shown next to the wording.
    """
    proxy=[]
    for f in findings or []:
        proxy.append({'claim_text':f.get('claim',''), 'claim_type':f.get('type','')})
    proxy=assign_claim_sources(proxy, page_segments, documents)
    for f, c in zip(findings or [], proxy):
        for k in ['source_url','source_label','audience_group','audience_lens','source_interpretation']:
            if c.get(k): f[k]=c[k]
    return findings

def split_red_flags_by_dimension(green_findings, social_findings, green_ext=None, social_ext=None, sector=None, audience=None):
    green=[]; social=[]
    green_groups={}; social_groups={}; empco_flag=False
    def concise_source(f):
        value=f.get('source_label') or f.get('source_url') or 'reviewed source'
        if str(value).lower().startswith(('http://','https://')):
            value=page_name_from_url(value)
        return re.sub(r'\s+',' ',str(value)).strip()[:90]
    for f in green_findings or []:
        if f.get('blacklisted_practice_indicator'):
            empco_flag=True
        if f.get('risk')!='High' or is_placeholder_finding(f.get('type','')):
            continue
        typ=f.get('type','Green claim'); row=green_groups.setdefault(typ,{'terms':[],'sources':[]})
        row['terms'].extend(f.get('problematic_terms') or [])
        row['sources'].append(concise_source(f))
    for typ,row in green_groups.items():
        terms=', '.join(list(dict.fromkeys(row['terms']))[:4]) or 'claim wording'
        sources=', '.join(list(dict.fromkeys(row['sources']))[:2])
        green.append(f"{typ}: review {terms}. Source{'s' if ', ' in sources else ''}: {sources}.")
    if empco_flag:
        green.append('Potential EmpCo issue: generic or high-sensitivity environmental wording may require clearer on-page specification and recognised supporting evidence.')
    for f in social_findings or []:
        if f.get('risk')!='High' or is_placeholder_finding(f.get('type','')):
            continue
        typ=f.get('type','Social claim'); row=social_groups.setdefault(typ,{'sources':[]})
        row['sources'].append(concise_source(f))
    for typ,row in social_groups.items():
        sources=', '.join(list(dict.fromkeys(row['sources']))[:2])
        social.append(f"{typ}: review scope, evidence and traceability. Source{'s' if ', ' in sources else ''}: {sources}.")
    if (green_ext or {}).get('targeted_negative_sources'):
        green.append(f"External green public-source signals retained: {len((green_ext or {}).get('targeted_negative_sources',[]))}. Verify relevance and contradiction risk manually.")
    if (social_ext or {}).get('targeted_negative_sources'):
        social.append(f"External social public-source signals retained: {len((social_ext or {}).get('targeted_negative_sources',[]))}. Verify relevance and contradiction risk manually.")
    if not green: green.append('No separate green red flag was retained beyond normal evidence and wording review.')
    if not social: social.append('No separate social red flag was retained beyond normal evidence and wording review.')
    return {'green':list(dict.fromkeys(green))[:5], 'social':list(dict.fromkeys(social))[:5]}


def green_claim_module(claim_type):
    t=(claim_type or '').lower()
    if 'generic' in t: return 'Generic Claim Detector'
    if 'climate' in t or 'offset' in t or 'carbon' in t: return 'Carbon / Offsetting Claim Check'
    if 'label' in t or 'certification' in t or 'visual' in t: return 'Label, Icon & Visual Claim Check'
    if 'future' in t: return 'Future Commitment Check'
    if 'comparative' in t: return 'Comparison Claim Check'
    if 'legal requirement' in t: return 'Legal Requirement Claim Check'
    if 'circular' in t or 'recycl' in t or 'durab' in t: return 'Circularity / Durability / Repairability Check'
    if 'absolute' in t or 'purity' in t: return 'Absolute Claim Check'
    return 'Green Claim Quality Check'

def green_blacklisted_indicator(claim_type, trigger, claim_text):
    t=(claim_type or '').lower(); c=(claim_text or '').lower(); trig=(trigger or '').lower()
    # v57o: EmpCo (Directive (EU) 2024/825) is not yet applicable -- it applies from 27 September
    # 2026 -- so these are readiness indicators for that date, not findings that the Annex I
    # blacklist has already been breached. Existing UCPD/national unfair-commercial-practices
    # rules may already be relevant today, independent of EmpCo's own applicability date.
    date_note=' (EmpCo readiness indicator, Directive (EU) 2024/825 applies from 27 September 2026)'
    if 'climate-neutrality' in t or 'offset' in t:
        # Annex I point 4c specifically targets a PRODUCT-level neutral/reduced/positive climate
        # claim that is BASED ON OFFSETTING -- a bare "climate/carbon neutral" claim with no
        # offset basis established in the retained wording is not automatically that practice;
        # it is still a case-by-case UCPD question until offsetting is confirmed as the basis.
        offset_established=any(x in c for x in ['offset','compensat','carbon credit','carbon-credit'])
        if offset_established:
            return 'High-priority EmpCo blacklisted-practice indicator where product-level neutral/reduced/positive climate impact is based on offsetting.'+date_note
        return ('Potential Annex I relevance -- offset basis not established from the retained wording alone. EmpCo Annex I point 4c '
                'specifically targets product-level neutral/reduced/positive climate-impact claims based on greenhouse-gas offsetting; '
                'this passage should be reviewed case-by-case under the general UCPD misleading-claims test unless an offset basis is confirmed.')
    if 'label' in t or 'certification' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the label/badge is not based on a qualifying certification scheme or not established by public authorities.'+date_note
    if 'generic environmental' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the generic claim is not clearly specified on the same medium and not backed by recognised excellent environmental performance.'+date_note
    if 'legal requirement' in t:
        return 'EmpCo blacklisted-practice indicator if legal compliance is presented as a distinctive environmental benefit.'+date_note
    if 'absolute' in t:
        return 'High overstatement indicator; can become misleading where the absolute claim is not fully substantiated for the full scope implied.'
    if 'comparative' in t:
        return 'High-risk comparison indicator where comparison method, comparator, source data and update process are missing.'
    return 'No direct blacklisted-practice indicator identified, but claim-specific substantiation is still required.'

def classify_legal_basis(f):
    """
    Splits every retained claim into exactly one of two legal-basis categories.
    This is a distinct axis from claim risk (High/Medium/Low) and from claim
    subject matter (green/social/forced-labour): it answers the question
    "is this wording automatically unfair, or does it depend on a case-by-case test?"

    - 'prohibited': the claim wording matches one of the fixed, per-se-unfair
      practices listed in EmpCo Annex I (self-declared sustainability labels
      without independent certification -- point 2a; unspecified generic
      environmental claims -- point 4a; aggregate/whole-product benefit claims
      based on only one aspect -- point 4b; product-level climate-neutral/
      reduced/positive claims based on offsetting -- point 4c; legal
      compliance presented as a distinctive feature -- point 10a). Once EmpCo
      applies (27 September 2026), these practices are automatically unfair if
      the described conditions are met -- no individual balancing test is
      needed, only whether the wording fits the listed practice.

    - 'problematic': the claim is not on that fixed list, so it is not
      automatically unfair -- but it is not a free pass either. It can still be
      found misleading after an individual, case-by-case assessment under the
      general UCPD provisions (Article 6 misleading actions, Article 7
      misleading omissions, or Article 6(2)(d) specifically for forward-looking
      claims). Critically, UCPD Art. 12/12a (reinforced by EmpCo) lets a court
      or authority REQUIRE the company to substantiate the claim's factual
      accuracy, and treats the claim as inaccurate/misleading for that
      assessment if adequate evidence is not supplied -- so once a claim is
      challenged, the evidentiary burden in practice sits with the company,
      not with the enforcer. This covers social/human-rights/labour claims,
      forced-labour readiness wording, absolute and comparative overstatements,
      and future environmental-performance claims -- the ultimate outcome
      still depends on context, evidence and consumer impact, not on a fixed
      rule, but "no evidence on hand" is a real liability here, not a neutral
      gap.
    """
    if bool(f.get('blacklisted_practice_indicator')):
        return {
            'legal_basis_category': 'prohibited',
            'legal_basis_label': 'Potentially Prohibited (EmpCo Annex I)',
            'legal_basis_short': ('On the fixed EmpCo Annex I list: automatically treated as unfair once EmpCo '
                                   'applies (27 September 2026) if the described conditions are met. No case-by-case '
                                   'balancing test is needed -- only whether the wording fits the listed practice.'),
        }
    return {
        'legal_basis_category': 'problematic',
        'legal_basis_label': 'Problematic, not automatically prohibited (case-by-case)',
        'legal_basis_short': ('Not on the fixed Annex I list, so not automatically unfair -- but under UCPD Art. '
                               '12/12a (reinforced by EmpCo), an authority or court can require the company to '
                               "substantiate the claim's factual accuracy, and the claim is treated as inaccurate/"
                               'misleading for that assessment if adequate evidence is not supplied. In practice, once '
                               'challenged, the burden falls on the company to produce evidence, not on the enforcer to '
                               'disprove the claim. Whether it is ultimately found misleading still depends on context, '
                               'evidence and consumer impact, and is not determined by this scan.'),
    }

def green_specification_check(claim_type, claim_text):
    c=(claim_text or '').lower(); t=(claim_type or '').lower()
    specificity_terms=['%', 'scope', 'baseline', 'compared with', 'compared to', 'made from', 'verified', 'certified', 'according to', 'methodology', 'life cycle', 'lca', 'for this product', 'packaging', 'valid until', 'standard', 'iso',
        'reikwijdte', 'nulmeting', 'referentiejaar', 'vergeleken met', 'gemaakt van', 'geverifieerd', 'gecertificeerd', 'volgens', 'methodologie', 'levenscyclus', 'voor dit product', 'verpakking', 'geldig tot', 'norm',
        'périmètre', 'année de référence', 'par rapport à', 'fabriqué à partir de', 'vérifié', 'certifié', 'selon', 'méthodologie', 'cycle de vie', 'pour ce produit', 'emballage', "valable jusqu'au", 'norme']
    has_specific=any(x in c for x in specificity_terms) or bool(re.search(r'\b\d{1,4}(?:[.,]\d+)?\s?%\b', c))
    if is_placeholder_finding(t):
        return {'status':'Not applicable','comment':'No material green claim was detected.'}
    if has_specific:
        return {'status':'Partly specified','comment':'Some specification indicators were found, but scope, methodology, limitations and evidence should still be reviewed.'}
    if any(x in t for x in ['generic','climate','comparative','future','label','absolute','legal requirement']):
        return {'status':'Likely insufficient','comment':'The detected wording appears broad or high-sensitivity and may lack clear, prominent same-medium specification.'}
    return {'status':'Needs review','comment':'The claim should be checked for precise scope, conditions and evidence.'}

def green_claim_evidence_questions(claim_type):
    t=(claim_type or '').lower()
    common=['What exact product, service, business unit or activity does the claim cover?','What objective data source supports the claim?','What reporting period, geography and limitations apply?','Who owns approval and periodic review of the claim?']
    if 'climate' in t or 'offset' in t:
        return common+['Is this a product-level or company-level claim?','Which GHG scopes and lifecycle stages are included?','What reductions were achieved versus baseline, and what role do offsets play?','Is the wording avoiding offset-based neutrality at product level?']
    if 'generic' in t:
        return common+['Is the generic wording specified clearly and prominently on the same medium?','Is there recognised excellent environmental performance relevant to the claim as a whole?']
    if 'label' in t or 'visual' in t:
        return common+['Who owns the scheme, and are its criteria transparent and publicly available?','Is the scheme open to any operator meeting the criteria on fair, reasonable and non-discriminatory terms?','Is compliance verified by an independent third party, with ongoing monitoring and a procedure for non-compliance?','Is this a public-authority-established label (e.g. EU Ecolabel), or a private scheme -- and is that distinction clear to the audience?','Could the visual presentation imply a broader benefit than the evidence supports?']
    if 'future' in t:
        return common+['Is the commitment clear, objective and publicly available (not just an internal ambition)?','Are the targets measurable and time-bound?','Is there a detailed, realistic implementation plan, including the resources allocated to deliver it?','Are there interim milestones to track progress against the target?','Is progress independently verified on a regular basis?','Are the verification findings publicly available?']
    if 'comparative' in t:
        return common+['What comparator is used?','Are products/suppliers compared on an equivalent basis?','How is the comparison kept up to date?']
    if 'legal requirement' in t:
        return common+['Is the statement merely legal compliance?','Is it presented separately from voluntary sustainability performance?']
    return common

def green_ready_to_use_rewrite(claim_type):
    """A literal, fill-in-the-blank example rewrite -- not abstract guidance on what to
    disclose, but an actual sentence structure the company can copy and complete with its own
    facts. Nothing inside [brackets] is invented or assumed true; it marks exactly what still
    needs to be supplied before the wording can be reused."""
    t=(claim_type or '').lower()
    if is_placeholder_finding(t):
        return ''
    if 'climate' in t or 'offset' in t:
        return ('"We have reduced our [Scope 1 and 2 / Scope 1, 2 and 3] emissions by [X%] since [baseline year], measured '
                 'according to [methodology, e.g. the GHG Protocol]. Remaining emissions are addressed through [name of '
                 'specific removal/offset programme]; details at [link]."')
    if 'label' in t or 'certification' in t:
        return ('"Certified [exact scheme name, e.g. GOTS / Fairtrade / EU Ecolabel] by [certifying body], certificate '
                 'number [X], valid until [date], covering [product/site scope]. Verify at [certifier registry link]."')
    if 'recycl' in t or 'circular' in t:
        return ('"Contains [X%] recycled [material] ([post-consumer/post-industrial]), verified per [standard, e.g. GRS], '
                 'covering [product/packaging scope]. Recyclable in [specific regions/facilities], subject to [conditions]."')
    if 'generic' in t:
        return ('"[Product/product line] uses [specific verified attribute, e.g. \'70% recycled cotton\'], based on '
                 '[methodology/standard], covering [this product only / this collection], as of [date]. Full methodology: '
                 '[link]."')
    if 'legal requirement' in t:
        return '"[Feature] complies with [specific law/regulation, e.g. EU REACH]."'
    if 'absolute' in t or 'purity' in t:
        return ('"[X%] of [specific scope, e.g. this product\'s packaging] is [specific attribute, e.g. recyclable '
                 'through standard municipal collection] in [region/market], based on [test standard/method]. [State any '
                 'exclusions or conditions]."')
    if 'comparative' in t:
        return ('"[Product] has [X%] lower [specific impact metric, e.g. CO2e per unit] than [named comparator or '
                 'previous version], based on [methodology/study, date], covering [scope of comparison]. Full data: [link]."')
    if 'future' in t:
        return ('"We aim to reach [specific target, e.g. net zero Scope 1 and 2] by [year], with an implementation plan '
                 'covering [key milestones], published at [link] and reviewed [annually / by whom]."')
    if 'visual' in t:
        return ('"[Icon/badge name] represents [specific certification scheme] awarded by [certifying body]; see [link] '
                 'for scope and criteria."')
    return ('"[Specific, verifiable statement], based on [methodology/standard/date], covering [exact scope]. Full '
            'evidence: [link]."')

_CORPORATE_LEVEL_MARKERS=['our operations','our company','our organisation','our organization','as a business',
    'group-wide','company-wide','across our business','our direct operations','our value chain','corporate level',
    'enterprise-wide','our whole business','the company','entire business','our business','operations',
    ' sites',' site ','our facilities','our factories','our sites','scope 1 and 2','scope 1, 2',
    'we are a climate neutral company','we are a carbon neutral company','our company is climate neutral',
    'our company is carbon neutral','is a climate neutral company','is a carbon neutral company',
    'we are climate neutral','we are carbon neutral','as an organisation','as an organization',
    'onze activiteiten','ons bedrijf','onze organisatie','als bedrijf','bedrijfsbreed','over ons hele bedrijf',
    'onze directe activiteiten','onze waardeketen','op ondernemingsniveau','onze vestigingen','onze fabrieken',
    'onze sites','wij zijn een klimaatneutraal bedrijf','wij zijn een koolstofneutraal bedrijf',
    'ons bedrijf is klimaatneutraal','ons bedrijf is koolstofneutraal','wij zijn klimaatneutraal',
    'wij zijn koolstofneutraal','als organisatie',
    'nos activités','notre entreprise','notre organisation','en tant qu\'entreprise','à l\'échelle du groupe',
    'dans toute notre entreprise','nos opérations directes','notre chaîne de valeur','au niveau de l\'entreprise',
    'nos sites','nos usines','nous sommes une entreprise neutre en carbone','notre entreprise est neutre en carbone',
    'nous sommes neutres en carbone','en tant qu\'organisation']

def _is_corporate_level_claim(claim_text):
    return any(m in (claim_text or '').lower() for m in _CORPORATE_LEVEL_MARKERS)

# Deliberately a narrower, stronger list than green_specification_check()'s general
# specificity_terms (which also counts a bare '%' or 'made from' -- fine for the informational
# "specification check" shown in the report, but too weak to safely downgrade a claim off the
# EmpCo Annex I 4a blacklist: "100% eco-friendly, made from sustainable materials" contains both
# a '%' and "made from" without actually specifying a verifiable attribute, methodology or scope).
_STRONG_SAME_MEDIUM_SPECIFICATION_TERMS=['according to','methodology','life cycle','lca','verified','certified',
    'compared with','compared to','baseline','valid until','iso ',' standard','third-party','independently verified',
    'volgens','methodologie','levenscyclus','geverifieerd','gecertificeerd','vergeleken met','nulmeting','geldig tot',
    ' norm','onafhankelijk geverifieerd','door derden geverifieerd',
    'selon','méthodologie','cycle de vie','vérifié','certifié','par rapport à','année de référence',
    "valable jusqu'au",' norme','vérifié par un tiers','vérifié de manière indépendante']

def _has_strong_same_medium_specification(claim_text):
    return any(x in (claim_text or '').lower() for x in _STRONG_SAME_MEDIUM_SPECIFICATION_TERMS)

def enrich_green_finding(f, trigger=''):
    f['module']=green_claim_module(f.get('type',''))
    f['specification_check']=green_specification_check(f.get('type',''), f.get('claim',''))
    f['regulatory_signal']=green_blacklisted_indicator(f.get('type',''), trigger, f.get('claim',''))
    sig=f['regulatory_signal'].lower(); f['blacklisted_practice_indicator']=(('blacklisted-practice indicator' in sig) and not sig.startswith('no direct'))
    t_low=f.get('type','').lower()
    # EmpCo Annex I point 4a only blacklists a GENERIC claim that lacks same-medium
    # specification; once genuine specification is present the claim is no longer "generic" in
    # the Annex I sense and moves to the general, case-by-case UCPD test instead (still
    # potentially misleading, but not an automatic Annex I match).
    if f['blacklisted_practice_indicator'] and 'generic' in t_low and _has_strong_same_medium_specification(f.get('claim','')):
        f['blacklisted_practice_indicator']=False
    # EmpCo Annex I point 4c specifically targets claiming that a PRODUCT has a neutral,
    # reduced or positive climate impact based on offsetting -- a company- or operations-wide
    # neutrality claim (e.g. "our direct operations reached carbon neutrality") is not on that
    # fixed list and remains a case-by-case UCPD assessment instead.
    if f['blacklisted_practice_indicator'] and ('climate' in t_low or 'offset' in t_low) and _is_corporate_level_claim(f.get('claim','')):
        f['blacklisted_practice_indicator']=False
    f.update(classify_legal_basis(f))
    f['evidence_questions']=green_claim_evidence_questions(f.get('type',''))
    f['ready_to_use_rewrite']=green_ready_to_use_rewrite(f.get('type',''))
    f['pre_publication_decision']='Do not publish/reuse without legal/compliance and evidence review.' if f.get('risk')=='High' and not is_placeholder_finding(f.get('type','')) else 'Can normally proceed only after standard evidence and wording review.'
    return f


def green_query_themes(findings):
    joined=' '.join((f.get('type','')+' '+f.get('claim','')).lower() for f in findings or [])
    # v77: NL/FR baseline themes go first, so they are never crowded out by the per-category
    # English themes below once the list is capped -- a company whose real press coverage is
    # mainly Dutch or French (common across the Benelux/France market this scan targets) would
    # otherwise never get searched in those languages at all. The post-hoc relevance filter
    # already recognises Dutch/French greenwashing vocabulary (_V71_GREEN_EXPLICIT etc.), but
    # that only helps once a search actually returns Dutch/French-language results to filter.
    themes=['misleidende duurzaamheidsclaim klacht greenwashing','greenwashing allégation environnementale trompeuse plainte']
    if 'climate' in joined or 'carbon' in joined or 'net zero' in joined: themes += ['greenwashing carbon neutral offset claim','net zero misleading advertising complaint']
    if 'generic' in joined or 'sustainable' in joined: themes += ['greenwashing sustainable claim advertising regulator','misleading environmental claim complaint']
    if 'comparative' in joined or 'lower' in joined: themes += ['misleading lower emissions comparison complaint','environmental comparison advertising claim']
    if 'label' in joined or 'certification' in joined: themes += ['sustainability label misleading certification complaint','eco label greenwashing']
    if 'circular' in joined or 'recycl' in joined or 'durab' in joined: themes += ['recyclable claim greenwashing complaint','circularity claim misleading advertising']
    if len(themes) <= 2: themes.append('greenwashing misleading environmental claims complaint')
    return list(dict.fromkeys(themes))[:9]


def summarise_green_ext(results):
    if not results: return 'No external public-source results were returned.'
    combo=' '.join((r.get('title','')+' '+r.get('content','')).lower() for r in results)
    terms=['greenwashing','misleading','advertising','regulator','complaint','lawsuit','court','authority','carbon neutral','offset','sustainable','recyclable','environmental claim']
    hits=[t for t in terms if t in combo]
    return ('External results contain potentially relevant green-claim signals, including: '+', '.join(hits[:8])+'. These require verification.') if hits else 'External results were found, but no strong green-claim risk signal was detected from snippets alone.'

GREEN_NEGATIVE_SIGNAL_TERMS=['greenwashing','misleading','complaint','lawsuit','court','regulator','authority','advertising standards','ban','prohibited','investigation','fine','penalty','sanction','watchdog','accused','allegation','criticised','criticized','consumer authority','settlement','asa','jep']


def green_evidence_signal_score(page_text, findings):
    text=(page_text or '').lower()
    if not text.strip() or (findings and is_placeholder_finding(findings[0].get('type',''))):
        return 75, ['No major green claim detected; evidence gap is not the main driver.']
    strong=['lca','life cycle','scope 1','scope 2','scope 3','baseline','methodology','verified','assurance','certified','iso','ghg protocol','science based','sbt','emissions data','recycled content','percentage','%','third party','audit','standard','criteria','valid until','implementation plan','transition plan','milestone','resources allocated']
    weak=['policy','commitment','aim','target','progress','initiative','programme','program']
    strong_hits=[t for t in strong if t in text]
    weak_hits=[t for t in weak if t in text]
    import re
    env_terms=['emissions','carbon','climate','recycled','recyclable','sustainable','environment','water','energy','waste','biodiversity','circular']
    numeric_env_hits=0
    for m in re.finditer(r'(\b\d{1,4}(?:[.,]\d+)?\s?%\b|\b20\d{2}\b)', text):
        win=text[max(0,m.start()-160):m.end()+160]
        if any(t in win for t in env_terms): numeric_env_hits+=1
    points=min(55,len(strong_hits)*7)+min(15,len(weak_hits)*3)+min(20,numeric_env_hits*5)
    substantiation=min(100,points)
    if substantiation>=75: note='Concrete website evidence was found for several EmpCo-relevant green-claim elements.'
    elif substantiation>=45: note='Some website evidence was found, but scope, methodology or verification may still be incomplete.'
    elif substantiation>=20: note='Limited website evidence was found; broad green claims should be better substantiated.'
    else: note='Little concrete website evidence was found around detected green claims.'
    hits=(strong_hits[:8]+weak_hits[:4]) or ['no concrete green evidence terms detected']
    return substantiation, [note, 'Detected green evidence indicators: '+', '.join(hits)+'.']

def green_external_context_risk(ext):
    if not ext or not ext.get('enabled'): return {'score':0,'note':'External green-source search not enabled.'}
    text=' '.join((r.get('title','')+' '+r.get('content','')+' '+r.get('url','')).lower() for r in ext.get('results',[]))
    if not text.strip(): return {'score':0,'note':'External green search returned no usable source signals.'}
    severe=['greenwashing','misleading','lawsuit','court','regulator','authority','fine','penalty','ban','prohibited','advertising standards','complaint']
    claim=['carbon neutral','offset','net zero','sustainable','recyclable','environmental claim','eco-friendly','climate neutral']
    sh=[t for t in severe if t in text]; ch=[t for t in claim if t in text]
    score=0
    if ch: score+=25
    if sh: score+=35
    if len(sh)>=2: score+=15
    if len(ch)>=2: score+=10
    return {'score':min(100,score),'note':('External green-context signals: '+', '.join((sh+ch)[:8])+'.') if score else 'External sources did not materially align with green-claim risk areas.'}

def sector_environment_score(sector):
    risks=(sector.get('risks','')+' '+sector.get('basis','')).lower()
    if any(t in risks for t in ['energy','gas','aviation','transport','chemical','manufacturing','industrial','apparel','food retail','commodity']): return 60
    if sector.get('level')=='High': return 55
    if sector.get('level')=='Medium': return 35
    return 15





def combine_green_social(green_score, social_score, audience):
    # Conservative integrated score: weighted average of green and social risk. It must not exceed the highest
    # dimension score and no longer receives a generic consumer-facing uplift.
    green=int(green_score or 0); social=int(social_score or 0)
    # Keep the global score close to the strongest dimension, but avoid automatic equality.
    if green==0 and social==0:
        return 0
    if green>=social:
        overall=round(green*0.58 + social*0.42)
    else:
        overall=round(green*0.42 + social*0.58)
    # If the dimensions are equal, keep equality; otherwise keep a distinct integrated score.
    return max(0, min(max(green, social), overall))

def green_washing_conclusion(score, findings, evidence_gap, external_score, audience):
    no_major=findings and is_placeholder_finding(findings[0].get('type',''))
    prefix='Consumer-facing EmpCo-relevant material: ' if ('Client-facing' in audience.get('audience','') or 'Consumer-facing' in audience.get('audience','') or 'commercial' in audience.get('audience','').lower()) else ''
    if no_major: return prefix+'No clear greenwashing signal detected'
    if score<30: return prefix+'Low green-claim substantiation risk'
    if score<50: return prefix+'Potentially overbroad green claim'
    if score<60: return prefix+'Potential greenwashing concern  -  evidence review needed'
    if external_score>=40 and evidence_gap>=55: return prefix+'High greenwashing risk signal  -  verify urgently'
    return prefix+'Potential greenwashing concern  -  not enough contradiction evidence for High'

def build_green_claim_inventory(findings):
    out=[]
    for f in findings:
        out.append({'dimension':'Green','claim_text':f.get('claim',''),'claim_type':f.get('type',''),'washing_type':f.get('type',''),'risk_level':f.get('risk',''),'claim_score':f.get('claim_score',0),'module':f.get('module',green_claim_module(f.get('type',''))),'risk_reason':f.get('issue',''),'analysis':f.get('issue',''),'matched_phrase':f.get('matched_phrase',''),'why_flagged':f.get('why_flagged',''),'regulatory_signal':f.get('regulatory_signal',''),'blacklisted_practice_indicator':f.get('blacklisted_practice_indicator',False),'legal_basis_category':f.get('legal_basis_category','problematic'),'legal_basis_label':f.get('legal_basis_label',''),'specification_check':f.get('specification_check',{}),'evidence_questions':f.get('evidence_questions',[]),'pre_publication_decision':f.get('pre_publication_decision','Review before publication.'),'evidence_needed':green_evidence_checklist(f),'suggested_rewrite':f.get('rewrite',''),'ready_to_use_rewrite':f.get('ready_to_use_rewrite',''),'standards':f.get('standards',[]),'problematic_terms':f.get('problematic_terms',[])})
    return out

def green_evidence_checklist(f):
    t=(f.get('type','')+' '+f.get('issue','')).lower()
    base=['scope of the claim','specific environmental attribute','reporting period','methodology','limitations and exclusions','verification or certification basis']
    if 'climate' in t or 'carbon' in t or 'offset' in t: return base+['emission scopes','baseline','actual reductions vs offsets','residual emissions','transition-plan milestones']
    if 'comparative' in t: return base+['comparator product/service','equivalent comparison basis','data date','maintenance of updated information']
    if 'label' in t or 'certification' in t: return base+['certification scheme owner','criteria','audit basis','validity period']
    if 'circular' in t or 'recycl' in t or 'durab' in t: return base+['product part covered','percentage content','local recycling/repair conditions','testing standard']
    return base+['objective evidence','publicly accessible substantiation']

def social_claim_inventory_with_dimension(findings):
    rows=build_claim_inventory(findings)
    for r in rows:
        r['dimension']='Social'
        # SOCIAL_WASHING_TAXONOMY's only "no claim" key is the legacy "No major high-risk
        # social claim detected" string, which the placeholder row never actually uses (it's
        # "No material problematic social claim retained") -- the .get() fallback silently
        # showed that raw, wordier type string instead of a clean "no signal" label.
        r['washing_type']=('No clear social-washing signal' if is_placeholder_finding(r.get('claim_type',''))
                            else SOCIAL_WASHING_TAXONOMY.get(r.get('claim_type',''),r.get('claim_type','')))
    return rows

def build_green_social_actions(green_findings, social_findings, audience, company_name=''):
    actions=[]
    cn=(company_name or '').strip()
    who=cn if cn and cn.lower() not in ('company reviewed','') else 'the company'
    client_facing=('Client-facing' in audience.get('audience','') or 'Consumer-facing' in audience.get('audience','') or 'commercial' in audience.get('audience','').lower())
    high_green=[f for f in (green_findings or []) if f.get('risk')=='High']
    high_social=[f for f in (social_findings or []) if f.get('risk')=='High']
    green_types=list(dict.fromkeys([f.get('type','') for f in (green_findings or []) if f.get('type') and not is_placeholder_finding(f.get('type',''))]))[:3]
    social_types=list(dict.fromkeys([f.get('type','') for f in (social_findings or []) if f.get('type') and not is_placeholder_finding(f.get('type',''))]))[:3]
    green_terms=list(dict.fromkeys([t for f in high_green for t in (f.get('problematic_terms') or [])]))[:5]
    social_terms=list(dict.fromkeys([t for f in high_social for t in (f.get('problematic_terms') or [])]))[:5]
    if client_facing or high_green:
        wording=f' Specific wording to check: {", ".join(green_terms)}.' if green_terms else ''
        areas='; '.join(green_types) or 'environmental claims'
        actions.append({'priority':'Priority 1','title':'Review client-facing green claims under EmpCo','action':f"Review {who}'s detected green claim areas ({areas}) across websites and product communication.{wording} Confirm the scope, methodology, current evidence, verification basis and limitations before reuse."})
    else:
        actions.append({'priority':'Priority 1','title':'Confirm which scanned claims are client-facing','action':f'Separate {who}\'s website/product/folder wording from annual or sustainability report language. Treat client-facing claims as higher priority for EmpCo-style substantiation and approval controls.'})
    if high_social:
        forced=any(('forced' in f.get('type','').lower() or 'modern slavery' in f.get('type','').lower() or 'supply' in f.get('type','').lower()) for f in high_social)
        wording=f' Specific wording to check: {", ".join(social_terms)}.' if social_terms else ''
        if forced:
            actions.append({'priority':'Priority 2','title':'Validate forced-labour and supplier claims','action':f"For {who}'s supplier and forced-labour assurances, confirm traceability, risk assessment, mitigation and remedy evidence relevant to Regulation (EU) 2024/3015.{wording}"})
        else:
            areas='; '.join(social_types) or 'social claims'
            actions.append({'priority':'Priority 2','title':'Substantiate high-priority social claims','action':f"For {who}'s detected social claim areas ({areas}), confirm scope, KPIs, grievance or remedy evidence, workforce data and limitations.{wording}"})
    actions.append({'priority':'Priority 3','title':'Build a claim evidence file','action':'Keep one evidence file per priority claim with the approved wording, source, owner, supporting evidence, review status and next review date.'})
    if any('comparative' in f.get('type','').lower() for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Check comparative green claims','action':f"For {who}'s reduced impact, lower emissions or better product wording, identify the comparator, baseline year, methodology, equivalent product basis and data date."})
    if any(('climate' in f.get('type','').lower() or 'offset' in f.get('type','').lower() or 'net zero' in f.get('claim','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Clarify climate and offset claims','action':f"Separate {who}'s actual emission reductions from offsetting/compensation, and disclose scopes, baseline, residual emissions, implementation plan and progress indicators."})
    if any(('label' in f.get('type','').lower() or 'certification' in f.get('type','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Verify labels and certifications','action':f"Name the scheme owner, criteria, certification scope, verification body and validity period for any green/social label or certification {who} references."})
    actions.append({'priority':'Priority 5','title':'Align reporting and marketing language','action':f"Use {who}'s reports as supporting evidence, but only reuse wording in consumer-facing communication when it is specific, current, substantiated and appropriate for that audience."})
    return actions[:6]



def discover_investor_internal_documents(company, reviewed_pages=None, limit=5):
    """Find company-owned annual/sustainability/ESG/policy sources for the investor/internal evidence lens.
    These are kept separate from external public-source signals. PDF content is not parsed by this lightweight hosted app;
    HTML pages may be crawled by the normal crawler when reachable.
    """
    if not (TAVILY_API_KEY or (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)):
        return []
    name=company.get('company','') if isinstance(company,dict) else str(company or '')
    queries=[
        f'{name} annual report sustainability report ESG report PDF',
        f'{name} human rights policy supplier code modern slavery statement PDF'
    ]
    out=[]; seen=set()
    for q in queries:
        try:
            res,attempts=search_public_sources(q,4)
        except Exception:
            res=[]
        for r in res:
            u=r.get('url','') or ''
            if not u or u in seen: continue
            if not is_company_owned_source(r, name, reviewed_pages):
                continue
            low=(r.get('title','')+' '+u+' '+r.get('content','')).lower()
            if not any(t in low for t in ['annual report','sustainability report','integrated report','esg report','human rights','supplier code','code of conduct','modern slavery','due diligence statement','policy']):
                continue
            seen.add(u)
            cls=classify_page_audience(u, r.get('title','')+' '+r.get('content',''))
            if cls.get('group') not in {'investor','internal'}:
                # force appropriate treatment for known company reports/policies
                if any(t in low for t in ['annual report','sustainability report','integrated report','esg report']):
                    cls={'audience':'Investor reporting','group':'investor','empco_relevance':'Indirect / evidence source','interpretation':'Company-owned report identified for investor/internal evidence review. It is not treated as an external stakeholder signal.'}
                else:
                    cls={'audience':'Policy / internal governance document','group':'internal','empco_relevance':'Indirect / governance evidence','interpretation':'Company-owned policy/governance source identified for evidence review. It is not treated as an external stakeholder signal.'}
            out.append({'name':page_name_from_url(u) if page_name_from_url(u)!=u else (r.get('title') or u)[:90], 'url':u, 'document_type':document_type_from_url(u), 'audience_assessment':cls.get('audience','Investor or internal document'), 'audience_group':cls.get('group','internal'), 'empco_relevance':cls.get('empco_relevance','Indirect'), 'interpretation':cls.get('interpretation','Company-owned investor/internal evidence source. Not counted as an external public-source signal.'), 'scan_status':'identified for evidence review'})
            if len(out)>=limit: break
        if len(out)>=limit: break
    return out

def merge_documents(primary, discovered):
    out=[]; seen=set()
    for d in (primary or [])+(discovered or []):
        u=d.get('url') or d.get('name')
        if not u or u in seen: continue
        seen.add(u); out.append(d)
    return out

def score_driver_details(green_score, social_score, green_fs, social_fs, green_splits, social_splits, green_components, social_components, green_ext, social_ext, sector, audience):
    def claim_names(fs):
        vals=[f.get('type','claim') for f in fs or [] if not is_placeholder_finding(f.get('type',''))]
        # v57i: previously each retained claim *instance* was listed by type name with no
        # de-duplication, so e.g. three separate "Aspirational or future social-performance
        # claim" excerpts showed up as that same phrase repeated three times in a row -- noisy
        # and harder to scan. Show each distinct claim type once, order-preserved, with a
        # (xN) count when it occurred more than once.
        counts={}; order=[]
        for v in vals:
            if v not in counts: order.append(v)
            counts[v]=counts.get(v,0)+1
        return [f'{v} (\u00d7{counts[v]})' if counts[v]>1 else v for v in order]
    def targeted_count(ext):
        return len(ext.get('targeted_negative_sources') or []) if ext else 0
    def band(n):
        n=n or 0
        return 'low' if n<25 else 'medium' if n<50 else 'high' if n<75 else 'very high'
    def dominant_driver(splits):
        labels={'claim_wording_risk':'the wording of the claims themselves','substantiation_risk':'a lack of visible evidence/substantiation','external_context_risk':'negative external signals','sector_baseline_risk':'sector-level exposure'}
        best=max(labels, key=lambda k: (splits or {}).get(k,0))
        return labels[best], (splits or {}).get(best,0)
    def material_count(fs):
        return len([f for f in fs or [] if not is_placeholder_finding(f.get('type',''))])
    def gap_label(value):
        value=int(value or 0)
        return 'limited' if value<30 else 'moderate' if value<60 else 'substantial'
    def external_line(count):
        return f'{count} qualifying negative external source(s) retained.' if count else 'No qualifying negative external source retained.'
    gnames=claim_names(green_fs); snames=claim_names(social_fs)
    g_top, g_top_val = dominant_driver(green_splits)
    s_top, s_top_val = dominant_driver(social_splits)
    client_facing='Client-facing' in audience.get('audience','') or 'Consumer-facing' in audience.get('audience','')
    g_ext_n=targeted_count(green_ext); s_ext_n=targeted_count(social_ext)
    if gnames:
        g_summary=f'Green risk is {green_score}/100 ({band(green_score)}). Main contribution: {g_top}.'
    else:
        g_summary=f'Green risk is {green_score}/100 ({band(green_score)}). No material green claim was retained.'
    if snames:
        s_summary=f'Social risk is {social_score}/100 ({band(social_score)}). Main contribution: {s_top}.'
    else:
        s_summary=f'Social risk is {social_score}/100 ({band(social_score)}). No material social claim was retained.'
    return {
        'green': {
            'score': green_score,
            'summary': g_summary,
            'key_drivers': [
                f'Claim wording — {material_count(green_fs)} relevant occurrence(s) across {len(gnames)} claim type(s).',
                f'Evidence support — {gap_label(green_splits.get("substantiation_risk",0))} visible evidence gap ({green_splits.get("substantiation_risk",0)}/100).',
                f'External context — {external_line(g_ext_n)}',
                ('Audience — consumer-facing wording increases EmpCo relevance.' if client_facing else 'Audience — reporting/internal wording is treated mainly as evidence context.')
            ]
        },
        'social': {
            'score': social_score,
            'summary': s_summary,
            'key_drivers': [
                f'Claim wording — {material_count(social_fs)} relevant occurrence(s) across {len(snames)} claim type(s).',
                f'Evidence support — {gap_label(social_splits.get("substantiation_risk",0))} visible evidence gap ({social_splits.get("substantiation_risk",0)}/100).',
                f'External context — {external_line(s_ext_n)}',
                'Regulatory context — forced-labour and supply-chain assurances receive higher weight where relevant.'
            ]
        }
    }


_DOCX_MAX_ENTRY_BYTES=20_000_000   # decompressed-size cap per zip entry
_DOCX_MAX_TOTAL_BYTES=40_000_000   # decompressed-size cap across all entries read

def _safe_zip_entry_read(zf, name, max_bytes):
    """Read a zip entry with a hard cap enforced during decompression, not just on the
    (attacker-controlled) declared size in the zip's central directory -- guards against a
    small compressed entry ('zip bomb') expanding to an enormous size in memory."""
    with zf.open(name) as f:
        chunks=[]; total=0
        while True:
            chunk=f.read(65536)
            if not chunk:
                break
            total+=len(chunk)
            if total>max_bytes:
                raise ValueError(f'"{name}" exceeds the maximum allowed decompressed size.')
            chunks.append(chunk)
        return b''.join(chunks)

def extract_docx_text(data):
    # v73: a DOCX is a zip archive, and reading an entry with ZipFile.read() decompresses it
    # fully into memory with no size cap -- a small, deliberately crafted compressed entry can
    # expand to a very large size ("decompression bomb"). Bound entry count, per-entry
    # decompressed size (checked both from declared metadata and enforced live during
    # streaming), and total decompressed bytes read across the whole document.
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts=[]; total_bytes=0
        extra=[n for n in z.namelist() if n.startswith('word/header') or n.startswith('word/footer')][:20]
        for name in ['word/document.xml']+extra:
            try:
                info=z.getinfo(name)
                if info.file_size>_DOCX_MAX_ENTRY_BYTES:
                    continue
                raw=_safe_zip_entry_read(z,name,_DOCX_MAX_ENTRY_BYTES)
                total_bytes+=len(raw)
                if total_bytes>_DOCX_MAX_TOTAL_BYTES:
                    break
                xml=raw.decode('utf-8',errors='ignore')
                xml=re.sub(r'<w:tab\s*/>', ' ', xml)
                xml=re.sub(r'</w:p>', '\n', xml)
                txt=re.sub(r'<[^>]+>', ' ', xml)
                parts.append(re.sub(r'\s+', ' ', txt))
            except Exception:
                pass
        return '\n'.join(parts).strip()

def extract_pdf_text_best_effort(data, max_pages=60):
    """PDF text extraction. Tries pypdf first, which correctly handles FlateDecode
    (the near-universal PDF compression method) and font encoding/ToUnicode maps -- the
    dominant case for professionally produced corporate PDFs (annual/CSR/ESG reports).
    Falls back to a lightweight regex-only scan (no dependency) if pypdf is unavailable or
    fails to parse the file, so a single malformed PDF cannot break the scan.
    max_pages bounds worst case processing time for very large reports on a hosted,
    time-limited deployment.
    """
    pypdf=_get_pypdf()
    if pypdf is not None:
        try:
            reader=pypdf.PdfReader(io.BytesIO(data))
            parts=[]
            n=min(len(reader.pages), max_pages)
            for i in range(n):
                try:
                    t=reader.pages[i].extract_text() or ''
                except Exception:
                    t=''
                if t: parts.append(t)
                if sum(len(p) for p in parts) > 200000:
                    break
            txt=' '.join(parts)
            txt=re.sub(r'\s+', ' ', txt).strip()
            if len(txt) >= 80:
                return txt[:90000]
            # pypdf ran but yielded almost nothing usable (e.g. scanned/image-only PDF) --
            # fall through to the regex fallback in case it can pull out something extra.
        except Exception:
            pass
    return _extract_pdf_text_regex_fallback(data)

def _extract_pdf_text_regex_fallback(data):
    """Best-effort extraction without any dependency. Decompresses FlateDecode content
    streams via the standard-library zlib module and pulls text-showing operator strings
    (Tj/TJ) from them; falls back further to any parenthesised literal string for very old
    or non-standard PDFs. Used only when pypdf is unavailable or fails."""
    import zlib
    text_parts=[]
    def text_operators(raw_bytes):
        try:
            raw=raw_bytes.decode('latin-1',errors='ignore')
        except Exception:
            return ''
        cands=re.findall(r'\(((?:[^()\\]|\\.)*)\)\s*T[jJ]', raw)
        if not cands:
            cands=re.findall(r'\(((?:[^()\\]|\\.)*)\)', raw)
        t=' '.join(cands)
        t=t.replace('\\n',' ').replace('\\r',' ').replace('\\t',' ')
        return re.sub(r'\\([()\\])', r'\1', t)
    try:
        for m in re.finditer(rb'stream\r?\n(.*?)endstream', data, re.DOTALL):
            try:
                # v86: zlib.decompress() has no output-size bound -- a small, crafted content
                # stream can decompress to a very large amount of memory (a classic
                # decompression-bomb DoS), and this fallback only runs on user-uploaded PDFs.
                # decompressobj().decompress(data, max_length) caps the OUTPUT size directly
                # (unlike the unbounded plain zlib.decompress), the same bounded-decompression
                # pattern already used for report tokens elsewhere in this file. 3MB per stream
                # is generous for real PDF text content -- the combined-text cap below is only
                # 200,000 chars anyway.
                decompressed=zlib.decompressobj().decompress(m.group(1),3_000_000)
            except Exception:
                continue
            text_parts.append(text_operators(decompressed))
            if sum(len(t) for t in text_parts) > 200000:
                break
        if not text_parts:
            text_parts.append(text_operators(data))
    except Exception:
        pass
    txt=re.sub(r'\s+', ' ', ' '.join(t for t in text_parts if t)).strip()
    return txt[:90000]

def decode_uploaded_document(filename, content_base64, mime_type=''):
    data=base64.b64decode(content_base64 or '')
    if len(data)>8_000_000:
        raise ValueError('Uploaded document is too large for this hosted first-pass scan. Please upload an extract below 8 MB.')
    name=(filename or 'uploaded_document').lower()
    if name.endswith('.docx') or 'wordprocessingml' in (mime_type or '').lower():
        txt=extract_docx_text(data)
    elif name.endswith('.pdf') or 'pdf' in (mime_type or '').lower():
        txt=extract_pdf_text_best_effort(data)
    else:
        txt=data.decode('utf-8',errors='ignore')
        if '<html' in txt[:500].lower() or '<body' in txt[:1000].lower():
            txt,_=parse_html(txt)
    txt=re.sub(r'[ \t]+',' ',txt or '')
    txt=re.sub(r'[ \t]*\n[ \t]*','\n',txt)
    txt=re.sub(r'\n{2,}','\n',txt).strip()
    if len(txt)<80:
        raise ValueError('The uploaded document could not be parsed into enough text. Please upload a text-based DOCX/HTML/TXT version or paste an extract into a text file.')
    return txt[:90000]

def fetch_document_text(url):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or is_private(p.hostname):
        return ''
    req=Request(url,headers={'User-Agent':CRAWLER_USER_AGENT,'Accept':'text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'},method='GET')
    with urlopen(req,timeout=10,context=ssl.create_default_context()) as r:
        ctype=(r.headers.get('content-type','') or '').lower()
        data=r.read(2500000)
    try:
        if 'html' in ctype or url.lower().endswith(('.html','.htm','/')):
            return parse_html(data.decode('utf-8',errors='ignore'))[0]
        if 'pdf' in ctype or url.lower().endswith('.pdf'):
            return extract_pdf_text_best_effort(data)
        if 'wordprocessingml' in ctype or url.lower().endswith('.docx'):
            return extract_docx_text(data)
        return data.decode('utf-8',errors='ignore')[:90000]
    except Exception:
        return ''

def collect_investor_internal_text(discovered_docs, limit=2):
    chunks=[]
    for d in (discovered_docs or [])[:limit]:
        u=d.get('url','')
        try:
            t=fetch_document_text(u)
            if t and len(t)>200:
                chunks.append('\n\nINVESTOR_OR_INTERNAL_DOCUMENT: '+u+'\n'+t[:18000])
                d['scan_status']='text extracted for investor/internal evidence scan'
            else:
                d['scan_status']='identified, but no extractable text retrieved'
        except Exception:
            d['scan_status']='identified, but retrieval failed'
    return '\n'.join(chunks)


def build_pre_publication_review(green_findings, social_findings, audience):
    rows=[]
    for f in green_findings or []:
        if is_placeholder_finding(f.get('type','')):
            continue
        rows.append({
            'dimension':'Green',
            'module':f.get('module', green_claim_module(f.get('type',''))),
            'claim_type':f.get('type',''),
            'claim_excerpt':f.get('claim',''),
            'risk_level':f.get('risk',''),
            'regulatory_signal':f.get('regulatory_signal',''),
            'specification_status':(f.get('specification_check') or {}).get('status','Needs review'),
            'decision':f.get('pre_publication_decision','Review before publication.'),
            'minimum_evidence_file':green_evidence_checklist(f),
            'safer_rewrite':f.get('rewrite','')
        })
    for f in social_findings or []:
        if is_placeholder_finding(f.get('type','')):
            continue
        rows.append({
            'dimension':'Social',
            'module':'Social Washing Claim Check',
            'claim_type':f.get('type',''),
            'claim_excerpt':f.get('claim',''),
            'risk_level':f.get('risk',''),
            'regulatory_signal':'Forced Labour Regulation / human-rights due-diligence lens' if has_forced_labour_regulatory_signal([f]) else 'Social-characteristics substantiation lens',
            'specification_status':'Needs evidence review',
            'decision':'Do not publish/reuse without evidence review.' if f.get('risk')=='High' else 'Proceed only after standard evidence and wording review.',
            'minimum_evidence_file':evidence_checklist(f),
            'safer_rewrite':f.get('rewrite','')
        })
    return rows[:20]

def build_regulatory_risk_summary(green_findings, social_findings, audience):
    green_flags=[f for f in green_findings or [] if f.get('blacklisted_practice_indicator')]
    social_flags=[f for f in social_findings or [] if has_forced_labour_regulatory_signal([f])]
    aud=(audience or {}).get('audience','Mixed or unclear')
    material=_material_findings(green_findings)+_material_findings(social_findings)
    prohibited=[f for f in material if f.get('legal_basis_category')=='prohibited']
    problematic=[f for f in material if f.get('legal_basis_category')=='problematic']
    # EmpCo amends the UCPD, which applies to business-to-consumer commercial practices --
    # not every passage in an annual report, investor presentation or internal policy document
    # automatically falls within that scope. When the reviewed material is mainly investor
    # reporting or internal/governance material (not mixed with client-facing content), make
    # that channel limitation explicit rather than implying direct EmpCo applicability.
    channel_caveat=''
    if str((audience or {}).get('empco_relevance','')).lower().startswith('indirect'):
        channel_caveat=(' The material reviewed in this scan is mainly ' + aud.lower() + ', not client-facing '
                         'commercial communication. EmpCo/UCPD applies most directly to consumer-facing claims, so '
                         'for this material the classifications below reflect wording-pattern screening and '
                         'substantiation risk rather than confirmed direct EmpCo applicability -- treat them as '
                         'general substantiation and reputational risk unless the same wording is reused externally.')
    return {
        'audience':aud,
        'empco_blacklisted_indicator_count':len(green_flags),
        'forced_labour_indicator_count':len(social_flags),
        'highest_priority':'EmpCo blacklisted-practice review' if green_flags else ('Forced Labour Regulation / social-claims review' if social_flags else 'Standard substantiation review'),
        'empco_indicators':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim',''), 'signal':f.get('regulatory_signal','')} for f in green_flags[:8]],
        'forced_labour_or_social_indicators':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim',''), 'signal':'Check product/supplier traceability, forced-labour risk assessment, remediation and response readiness.'} for f in social_flags[:8]],
        'legal_basis_breakdown':{
            'prohibited_count':len(prohibited),
            'problematic_count':len(problematic),
            'prohibited_label':'Potentially Prohibited (EmpCo Annex I)',
            'problematic_label':'Problematic, not automatically prohibited (case-by-case)',
            'explanation':('Two different legal tests apply to sustainability claims. "Potentially Prohibited" claims match the '
                            'wording of a fixed list in EmpCo Annex I (self-declared labels, generic claims, offset-based neutrality '
                            'claims, legal compliance presented as a benefit) as detected by this automated screening; practices that '
                            'actually meet the described conditions become automatically unfair once EmpCo applies on 27 September '
                            '2026, with no case-by-case balancing test -- but this flags the wording pattern only, not a confirmed '
                            'finding. "Problematic" claims are not on that fixed list but can still be found misleading after an '
                            'individual assessment under general UCPD rules (Art. 6/7, or Art. 6(2)(d) for future claims) -- the '
                            'outcome depends on context, evidence and consumer impact.' + channel_caveat),
            'prohibited_examples':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim','')} for f in prohibited[:5]],
            'problematic_examples':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim','')} for f in problematic[:5]],
        },
        'note':'This is a screening signal. It does not establish a legal breach, but it identifies claims that should be reviewed before publication or reuse.'
    }

def build_claim_modules_summary(green_findings, social_findings):
    modules={}
    # The green loop previously had NO placeholder guard at all (the social loop below at
    # least attempted one, just with the broken "no major" prefix) -- a document with zero
    # real green claims still counted its "No material problematic green claim retained"
    # placeholder as one claim-module signal.
    for f in green_findings or []:
        if is_placeholder_finding(f.get('type','')):
            continue
        m=f.get('module', green_claim_module(f.get('type','')))
        modules.setdefault(m, {'count':0,'risk_levels':[],'claim_types':[]})
        modules[m]['count']+=1; modules[m]['risk_levels'].append(f.get('risk','')); modules[m]['claim_types'].append(f.get('type',''))
    if social_findings and not is_placeholder_finding(social_findings[0].get('type','')):
        modules.setdefault('Social Washing Claim Check', {'count':0,'risk_levels':[],'claim_types':[]})
        for f in social_findings:
            if is_placeholder_finding(f.get('type','')):
                continue
            modules['Social Washing Claim Check']['count']+=1; modules['Social Washing Claim Check']['risk_levels'].append(f.get('risk','')); modules['Social Washing Claim Check']['claim_types'].append(f.get('type',''))
    out=[]
    for m,v in modules.items():
        out.append({'module':m,'detected_claims':v['count'],'highest_risk':'High' if 'High' in v['risk_levels'] else ('Medium' if 'Medium' in v['risk_levels'] else 'Low'),'claim_types':list(dict.fromkeys(v['claim_types']))[:5]})
    return out

def federation_pilot_output(green_findings, social_findings, overall, green_score, social_score):
    return {
        'member_scan_positioning':'Sustainability Claims Risk Scan',
        'member_value':'Identifies risky, vague or insufficiently substantiated claims before they are used in websites, campaigns, packaging, brochures or sustainability communication.',
        'benchmark_fields':['overall_score','green_score','social_score','number_of_empco_indicators','number_of_forced_labour_or_social_indicators','top_claim_modules','priority_actions'],
        'aggregatable_for_federations':True,
        'example_sector_output':'A federation can run the same scan across a small sample of member websites and receive an anonymised benchmark of most common claim risks.'
    }

def analyse_uploaded_document(filename, text, company_name_hint=''):
    source='Uploaded internal document: '+(filename or 'document')
    comp=infer_company(filename or source, text, company_name_hint)
    audience=classify_document_audience(filename or source, text, [source])
    # Uploaded internal documents should not be treated as consumer-facing unless wording clearly says marketing/product/brochure.
    if audience.get('group')=='mixed':
        audience={'audience':'Investor or internal document','group':'internal','empco_relevance':'Indirect / evidence source','note':'Uploaded non-public document. Treated primarily as internal evidence, governance and consistency context unless claim wording is clearly consumer-facing.'}
    documents_checked=[{'name':filename or 'uploaded document','url':source,'document_type':'Uploaded internal document','audience_assessment':audience.get('audience','Internal document'),'audience_group':audience.get('group','internal'),'empco_relevance':audience.get('empco_relevance','Indirect'),'interpretation':'User-uploaded internal company document scanned for claim wording and substantiation gaps.'}]
    scan_inventory=build_scan_inventory([source],documents_checked,[],full_text=text)
    page_segments=[{'url':source,'text':text}]
    social_fs=detect_claims(text)
    green_fs=detect_green_claims(text)
    green_fs=assign_sources_to_findings(green_fs,page_segments,documents_checked)
    social_fs=assign_sources_to_findings(social_fs,page_segments,documents_checked)
    # Separate internal-document scan: no website content and no external public-source search.
    social_ext={'enabled':False,'results':[],'compact_sources':[],'targeted_negative_sources':[],'summary':'External public-source search is not performed for internal-document scans.'}
    green_ext={'enabled':False,'results':[],'compact_sources':[],'targeted_negative_sources':[],'summary':'External public-source search is not performed for internal-document scans.'}
    social_targeted=[]
    green_targeted=[]
    exttext=''
    sec=infer_sector(comp,text,page_segments)
    ctx=infer_context(comp,text,social_ext)
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext,text,comp.get("company",""),audience,page_segments)
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext,text,audience,page_segments)
    social_splits=split_scores(social_fs,sec,ctx,social_mod,social_components)
    green_splits={k:green_components[k] for k in ['claim_wording_risk','substantiation_risk','external_context_risk','sector_baseline_risk']}
    overall=combine_green_social(green_score,social_score,audience)
    all_claims=build_green_claim_inventory(green_fs)+social_claim_inventory_with_dimension(social_fs)
    for c in all_claims:
        c.setdefault('source_url', source); c.setdefault('source_label', filename or 'Uploaded document'); c.setdefault('audience_lens', audience.get('audience','Internal document')); c.setdefault('audience_group', audience.get('group','internal'))
    attach_claim_counts_to_inventory(scan_inventory, all_claims)
    green_conclusion=green_washing_conclusion(green_score,green_fs,green_splits.get('substantiation_risk',50),green_splits.get('external_context_risk',0),audience)
    social_conclusion=washing_conclusion(social_score,social_fs,social_splits.get('substantiation_risk',50),social_splits.get('external_context_risk',0))
    methodology='Sustainability Claims Risk Scan. This is a separate internal-document scan. The uploaded file is assessed on its own and is not combined with website content or external public-source search. Internal documents are assessed mainly for claim wording, substantiation gaps, governance evidence, consistency risks and potential future reuse in client-facing communication. Scores use a continuous calibrated calculation method: claim wording, evidence gap, retained external stakeholder context, sector/channel sensitivity and direct EmpCo or Forced Labour Regulation indicators.'
    summary=(f"The scan reviewed the uploaded document for {comp['company']} and identified a {level(overall).lower()} "
             f"overall sustainability-claim risk ({overall}/100). Green-claim risk is {green_score}/100; "
             f"social-claim risk is {social_score}/100. The main priorities are the retained wording and the "
             "evidence available to support it. This is an initial screening result, not a legal finding.")
    return {'version':APP_VERSION,'assessment_type':'internal_document','document_type':'Uploaded internal document','source_label':source,'original_url':source,'fallback_note':'','analysis_date':datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
        'overall_score':overall,'overall_risk':level(overall),'global_score':overall,'global_risk':level(overall),'green_score':green_score,'green_risk':level(green_score),'green_conclusion':green_conclusion,'social_score':social_score,'social_risk':level(social_score),'social_conclusion':social_conclusion,'screening_conclusion':f'Global: {level(overall)} | Green: {level(green_score)} | Social: {level(social_score)}','methodology':methodology,'company':comp,'sector':sec,'context':ctx,'document_audience':audience,'findings':all_claims,'green_findings':green_fs,'social_findings':social_fs,'documents_checked':documents_checked,'scan_inventory':scan_inventory,'channel_analysis':build_channel_analysis(documents_checked),'related_source_notes':[],'report':{'summary':summary,'rationale':methodology,'rewrite_guidance':'Make green and social claims specific, scoped, evidenced and audience-appropriate.','pages_reviewed':[source],'standards_overview':EMPCO_LENS+STANDARDS},'assessment_summary_specific':summary,'concise_standards_lens':EMPCO_LENS,'merged_claims':all_claims,'claim_inventory':all_claims,'regulatory_risk_summary':build_regulatory_risk_summary(green_fs,social_fs,audience),'claim_modules_summary':build_claim_modules_summary(green_fs,social_fs),'federation_pilot_output':federation_pilot_output(green_fs,social_fs,overall,green_score,social_score),'external_research':{'green':dict(green_ext,compact_sources=green_targeted,targeted_negative_sources=green_targeted),'social':dict(social_ext,compact_sources=social_targeted,targeted_negative_sources=social_targeted),'summary':'Internal-document scan only. No public-source or website content is included.'},'green_external_context_assessment':green_external_context,'social_external_context_assessment':{'score':0,'note':'Not assessed for internal-document scans.'},'score_components':{'green':green_components,'social':social_components},'split_scores':{'global_score':overall,'green_risk_score':green_score,'social_risk_score':social_score,'green':green_splits,'social':social_splits},'why_score':{'global':f'Global score is {overall}/100. It reflects only the uploaded internal document and is a weighted combination of the green and social scores.','green':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['green']['summary'],'social':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['social']['summary'],'audience':audience.get('note',''),'interpretation':'This is an assessment signal, not a legal finding.'},'score_driver_details':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext,sec,ctx)+(['EmpCo readiness flag (applies from 27 September 2026): high-sensitivity green claims should be prepared for EmpCo-style substantiation and wording controls ahead of that date.'] if any(f.get('risk')=='High' for f in green_fs) else []),'red_flags_by_dimension':split_red_flags_by_dimension(green_fs,social_fs,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'company_action_plan':build_green_social_actions(green_fs,social_fs,audience,comp.get('company','')),'engagement_questions':build_engagement_questions(social_fs,social_ext),'confidence':{'level':'Medium','reasons':['Uploaded document was scanned as a standalone source.','External public-source search was not performed for this internal-document scan.']},'disclaimer':'Indicative first-pass sustainability claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use.','analysed_text_excerpt':text[:2200],'quality_improvements':['Maintain a sustainability claims register distinguishing green and social claims, claim owner, evidence file and review date.','Attach objective evidence, same-medium specification, methodology, limitations and approval owner to each claim.'],'ai_used':False,'ai_note':''}

def _describe_fetch_error(err):
    """Turns a raw fetch exception into a clear, non-technical explanation."""
    if isinstance(err, HTTPError):
        if err.code in (401, 403):
            return (f'the website returned HTTP {err.code} ({("Unauthorized" if err.code==401 else "Forbidden")}). '
                    'This usually means the site has bot-detection or firewall protection that blocks automated '
                    'requests, not that the scan is broken. Try scanning a specific sub-page instead of the homepage, '
                    'or check the site manually.')
        if err.code == 429:
            return 'the website returned HTTP 429 (Too Many Requests). The site is rate-limiting automated requests; try again later.'
        if err.code >= 500:
            return f'the website returned HTTP {err.code}, a server-side error on the site itself.'
        return f'the website returned HTTP {err.code}.'
    if isinstance(err, URLError):
        reason = str(getattr(err, 'reason', err))
        if 'not known' in reason.lower() or 'nodename' in reason.lower():
            return 'the domain name could not be resolved (it may not exist, or may be misspelled).'
        if 'timed out' in reason.lower():
            return 'the connection timed out before the site responded.'
        return f'a connection error occurred ({reason}).'
    return str(err)


def analyse_url_v27(raw):
    original_url,resolution_note=resolve_scan_input(raw); fallback_note=resolution_note or ''; related_notes=[]
    company_name_hint=_v65_scan_input_company_hint(raw, original_url)
    scan_deadline=time.time()+CRAWL_BUDGET_SECONDS
    try:
        try:
            txt,pages,related_notes,crawl_log=crawl_with_related_sites(original_url,overall_deadline=scan_deadline,company_name_hint=company_name_hint)
        except TypeError as crawl_type_error:
            if 'company_name_hint' not in str(crawl_type_error): raise
            txt,pages,related_notes,crawl_log=crawl_with_related_sites(original_url,overall_deadline=scan_deadline)
        url=original_url
    except Exception as first_error:
        raise ValueError(f'Could not scan {original_url}: {_describe_fetch_error(first_error)} No country-domain substitution was attempted; verify the exact official URL and try again.')
    comp=infer_company(url,txt,company_name_hint)
    page_segments=extract_page_segments(txt,pages)
    audience=classify_document_audience(url,txt,pages)
    documents_checked=build_documents_checked(pages,audience,txt)
    scan_inventory=build_scan_inventory(pages,documents_checked,crawl_log,full_text=txt)
    discovered_docs=[]
    try:
        discovered_docs=[]  # v53: skip secondary investor-document discovery during live website scans to avoid Render gateway timeouts
    except Exception:
        discovered_docs=[]
    documents_checked=merge_documents(documents_checked, discovered_docs)
    investor_internal_text=""  # v53: keep website scan focused on crawled website pages
    if investor_internal_text:
        txt=(txt+'\n'+investor_internal_text)[:110000]
    page_segments=extract_page_segments(txt,pages)
    channel_analysis=build_channel_analysis(documents_checked)
    # v45 fix: detect claim findings before assigning sources. In v44, source assignment
    # was called before green_fs/social_fs existed, which caused the scan to fail for
    # some websites with: cannot access local variable 'green_fs'.
    social_fs=detect_claims(txt)
    green_fs=detect_green_claims(txt)
    green_fs=assign_sources_to_findings(green_fs,page_segments,documents_checked)
    social_fs=assign_sources_to_findings(social_fs,page_segments,documents_checked)
    # Website scans should include external public-source signals. Uploaded internal
    # documents remain separate and do not run external search in analyse_uploaded_document().
    social_ext=external(comp['company'], social_fs, pages)
    green_ext=external_green(comp['company'], green_fs, pages)
    exttext=' '.join(r.get('title','')+' '+r.get('content','') for r in (social_ext.get('results',[])+green_ext.get('results',[])))
    sec=infer_sector(comp,txt+'\n'+exttext,page_segments,url)
    ctx=infer_context(comp,txt,social_ext)
    # v84: was capped at 5 -- this same capped list both fed the risk score AND was the only
    # thing ever eligible to reach the report/frontend, even though _v60_rank_dedupe below can
    # retain up to limit*3 candidates. Raised to 10; strict_external_context_risk's thresholds
    # already saturate at >=3 matching signals, so this mainly widens what gets SHOWN, not the
    # score.
    social_targeted=targeted_negative_sources(social_ext.get('results',[]), comp.get('company',''), 10, [d.get('url') for d in documents_checked], is_negative_external_source)
    green_targeted=targeted_negative_sources(green_ext.get('results',[]), comp.get('company',''), 10, [d.get('url') for d in documents_checked], is_green_negative_source)
    # Score and display only retained external stakeholder signals. Company-owned policies,
    # reports and sustainability pages are deliberately excluded from this layer.
    social_ext_scoring=dict(social_ext, results=social_targeted, compact_sources=social_targeted, targeted_negative_sources=social_targeted)
    green_ext_scoring=dict(green_ext, results=green_targeted, compact_sources=green_targeted, targeted_negative_sources=green_targeted)
    # v57o: an external-context score of 0 can mean two very different things -- "we searched
    # and found no negative signal" (a genuine, informative result) or "external search was not
    # configured/enabled for this scan" (no information at all). Silently treating both as the
    # same "0" risk contribution overstates confidence in scans where no search ran. Surface
    # this explicitly rather than letting the numeric score imply a verification that did not
    # happen.
    def _ext_verification_status(ext, targeted):
        if not (ext or {}).get('enabled'):
            return 'Not performed (no external search source was configured for this scan)'
        if targeted:
            return f'Performed \u2014 {len(targeted)} relevant external signal(s) retained'
        return 'Performed \u2014 no relevant external signal identified'
    external_verification_status={'green':_ext_verification_status(green_ext, green_targeted), 'social':_ext_verification_status(social_ext, social_targeted)}
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext_scoring,txt,comp.get("company",""),audience,page_segments)
    social_external_context = strict_external_context_risk({'results':social_targeted}, comp.get('company',''))
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext_scoring,txt,audience,page_segments)
    overall=combine_green_social(green_score,social_score,audience)
    social_splits=split_scores(social_fs,sec,ctx,social_mod,social_components)
    green_splits={k:green_components[k] for k in ['claim_wording_risk','substantiation_risk','external_context_risk','sector_baseline_risk']}
    social_conclusion=washing_conclusion(social_score,social_fs,social_splits.get('substantiation_risk',50),social_splits.get('external_context_risk',0))
    green_conclusion=green_washing_conclusion(green_score,green_fs,green_splits.get('substantiation_risk',50),green_splits.get('external_context_risk',0),audience)
    all_claims=build_green_claim_inventory(green_fs)+social_claim_inventory_with_dimension(social_fs)
    all_claims=assign_claim_sources(all_claims,page_segments,documents_checked)
    for c in all_claims:
        # v57v: .setdefault() only fills in a key that is entirely absent -- it does not replace
        # an existing falsy value. assign_claim_sources() can legitimately set source_url to ''
        # when no page matched confidently, so that empty string was silently surviving instead
        # of falling back to the scanned URL as intended. Explicitly check for falsy values too.
        if not c.get('source_url'):
            c['source_url']=url
        if not c.get('source_label'):
            c['source_label']=page_name_from_url(url) if url else 'Reviewed website / document'
        c.setdefault('audience_lens', audience.get('audience','Mixed or unclear'))
        c.setdefault('audience_group', 'mixed')
    attach_claim_counts_to_inventory(scan_inventory, all_claims)
    methodology='Sustainability Claims Risk Scan. The assessment separates green and social claim signals. Green claims are assessed through an EmpCo / Directive (EU) 2024/825 lens for consumer-facing environmental claims (Member States must transpose by 27 March 2026; rules apply from 27 September 2026), with explicit modules for generic claims, carbon/offsetting, labels/icons, future claims, comparisons, legal-requirement claims and same-medium specification. Social claims are assessed through claim wording, evidence gap, external contradictory context and sector exposure, with a specific Forced Labour Regulation / Regulation (EU) 2024/3015 lens for product, supplier, import/export, traceability, forced-labour and modern-slavery claims (core prohibition and enforcement provisions apply from 14 December 2027; this is a market-access/customs regime, not a claims law, and creates no new due-diligence obligation of its own per Art. 1(3)). Clear indications of EmpCo or Forced Labour Regulation risk receive a higher weighting than broader responsible-business claims mainly linked to OECD Guidelines, UNGC or UNGP expectations. External public-source signals exclude company-owned websites, policies, reports and supplier documents; those may be used as evidence but not as external stakeholder signals. Sector exposure is included as a baseline sensitivity factor but should not create a High-risk result without problematic claim wording, evidence gaps or contradictory context.'
    confidence_result=build_confidence(pages,social_ext,social_fs,crawl_log)
    reliability_warning=confidence_result.get('reliability_warning')
    # Use the same expected-guess-filtered counts the warning text itself is based on (see
    # build_confidence), so the "(X/Y pages failed)" prefix never disagrees with the warning
    # sentence next to it.
    crawl_pages_attempted=confidence_result.get('attempted',len(crawl_log))
    crawl_pages_failed=confidence_result.get('blocked',len([e for e in crawl_log if not e.get('ok')]))
    crawl_pages_thin=len([e for e in crawl_log if e.get('ok') and e.get('thin')])
    domains_covered=len({(urlparse(p).hostname or '') for p in pages if p})
    summary=(f"The scan reviewed {len(pages)} public page(s) across {max(1,domains_covered)} domain(s) for {comp['company']} and identified "
             f"a {level(overall).lower()} overall sustainability-claim risk ({overall}/100). "
             f"Green-claim risk is {green_score}/100; social-claim risk is {social_score}/100. "
             "The main review priorities are the retained claim wording and the visible evidence supporting it. "
             "This is an initial screening result, not a legal finding.")
    if not (green_ext or {}).get('enabled') and not (social_ext or {}).get('enabled'):
        summary=summary+" Note: external public-source verification was not performed for this scan (no search source configured); the external-context component reflects that no check was run, not a confirmed absence of negative signals."
    if reliability_warning:
        summary=f"⚠ DATA RELIABILITY: {reliability_warning} " + summary
    screening_conclusion=f'Global: {level(overall)} | Green: {level(green_score)} | Social: {level(social_score)}'
    if reliability_warning:
        screening_conclusion=f'⚠ Low confidence ({crawl_pages_failed}/{crawl_pages_attempted} pages failed) | '+screening_conclusion
    entity_context_indicator=build_entity_context_indicator(sec, ctx, green_targeted, social_targeted, external_verification_status)
    return {'version':APP_VERSION,'source_label':url,'original_url':original_url,'fallback_note':fallback_note,'analysis_date':datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
        'overall_score':overall,'overall_risk':level(overall),'global_score':overall,'global_risk':level(overall),
        'green_score':green_score,'green_risk':level(green_score),'green_conclusion':green_conclusion,
        'social_score':social_score,'social_risk':level(social_score),'social_conclusion':social_conclusion,
        'screening_conclusion':screening_conclusion,
        'data_reliability_warning':reliability_warning,
        'crawl_diagnostics':{'pages_attempted':crawl_pages_attempted,'pages_failed':crawl_pages_failed,'pages_thin':crawl_pages_thin,'pages_retrieved_via_fallback':len([e for e in crawl_log if e.get('ok') and e.get('method')=='reader_fallback']),'detail':crawl_log},
        'methodology':methodology,'company':comp,'sector':sec,'context':ctx,'document_audience':audience,
        'findings':all_claims,'green_findings':green_fs,'social_findings':social_fs,
        'documents_checked':documents_checked,'scan_inventory':scan_inventory,'channel_analysis':channel_analysis,'related_source_notes':related_notes,
        'report':{'summary':summary,'rationale':methodology+' '+audience['note'],'rewrite_guidance':'Make green and social claims specific, scoped, evidenced, audience-appropriate and consistent with public information. For forced-labour or modern-slavery wording, avoid implying product/supply-chain assurance unless traceability, risk assessment, remediation and response evidence is available.','pages_reviewed':pages,'standards_overview':EMPCO_LENS+STANDARDS},
        'assessment_summary_specific':summary,'concise_standards_lens':EMPCO_LENS,
        'merged_claims':all_claims,'claim_inventory':all_claims,
        'regulatory_risk_summary':build_regulatory_risk_summary(green_fs,social_fs,audience),'claim_modules_summary':build_claim_modules_summary(green_fs,social_fs),'federation_pilot_output':federation_pilot_output(green_fs,social_fs,overall,green_score,social_score),
        'external_research':{'green':dict(green_ext,compact_sources=green_targeted,targeted_negative_sources=green_targeted),'social':dict(social_ext,compact_sources=social_targeted,targeted_negative_sources=social_targeted),'summary':'Green and social external-source layers are reported separately.'},
        'green_external_context_assessment':green_external_context,'social_external_context_assessment':social_external_context,
        'score_components':{'green':green_components,'social':social_components},'split_scores':{'global_score':overall,'green_risk_score':green_score,'social_risk_score':social_score,'green':green_splits,'social':social_splits},
        'why_score':{'global':f'Global score is {overall}/100. It is a weighted combination of the green score ({green_score}/100) and social score ({social_score}/100), calibrated so that one dimension does not automatically dominate the global score. Direct EmpCo or Forced Labour Regulation risk signals can raise the relevant dimension score, while broader OECD/UNGC/UNGP expectations are weighted less strongly.',
                     'green':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience)['green']['summary'],
                     'social':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience)['social']['summary'],
                     'audience':audience['note'],'interpretation':'This is an assessment signal, not a legal finding. EmpCo relevance is strongest for consumer-facing commercial communications. The score methodology uses continuous weighting so results vary by claim type, evidence gap, communication channel, sector sensitivity and retained external stakeholder context.'},
        'score_driver_details':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience),
        'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext_scoring,sec,ctx),
        'red_flags_by_dimension':split_red_flags_by_dimension(green_fs,social_fs,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),
        'company_action_plan':build_green_social_actions(green_fs,social_fs,audience,comp.get('company','')),'engagement_questions':build_engagement_questions(social_fs,social_ext)+['Which green claims are consumer-facing, and what objective evidence file supports each claim under EmpCo-style controls?','For products or supply chains, what forced-labour risk assessment, traceability evidence, remediation process and withdrawal/customs response procedure support the claim under Regulation (EU) 2024/3015?'],
        'confidence':confidence_result,'external_verification_status':external_verification_status,'entity_context_indicator':entity_context_indicator,'disclaimer':'Indicative first-pass sustainability claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use. External search results are review signals that require manual verification.',
        'analysed_text_excerpt':txt[:2200],'quality_improvements':['Maintain a sustainability claims register distinguishing green and social claims, claim owner, evidence file and review date.','Classify each claim by audience: consumer-facing marketing vs investor reporting.','For forced-labour and modern-slavery claims, link wording to product/supplier traceability, risk assessment, remediation and Regulation (EU) 2024/3015 readiness.','Attach objective evidence, same-medium specification, methodology, limitations and approval owner to each claim.','Check public-source context for contradiction signals and keep company-owned evidence separate from external stakeholder sources.'],
        'ai_used':False,'ai_note':''}



# -----------------------------
# V52 MATERIAL CLAIMS AND CALIBRATED SCORING OVERRIDES
# -----------------------------
# The Sustainability Scan now retains only material claim-risk signals: direct EmpCo
# blacklisted-practice indicators, high-sensitivity environmental wording, or social
# claims that imply assurance/control over human rights, labour, suppliers, traceability,
# forced labour or equivalent sensitive matters. Neutral mentions are not shown as claim
# risks and do not drive the score.

# Narrower EmpCo/green-claim taxonomy. General ESG words are not retained unless the
# wording is an actual high-sensitivity claim or a direct blacklisted-practice indicator.

# Narrower social taxonomy. Supplier/customer/community mentions are not retained unless
# they imply assurance, coverage, control, certification, traceability, rights protection or
# equivalent high-stakes social performance.

def _sentence_window(text, trig):
    return clean_excerpt(text, trig)

def _has_real_claim_context(excerpt, typ, trig):
    c=(excerpt or '').lower(); t=(typ or '').lower(); trig=(trig or '').lower()
    # Avoid retaining navigation/header/footer fragments or isolated generic category names.
    if len(c.strip()) < 35:
        return False
    if 'supply-chain' in t or 'supplier' in t:
        strong=['all suppliers','100% of suppliers','audited','certified','comply','compliant','meet our standards','ethical sourcing','responsible sourcing','traceable','traceability','supplier code','due diligence','human rights','forced labour','forced labor','child labour','child labor']
        neutral=['backing british suppliers','supporting local suppliers','working with suppliers','our suppliers','supplier information','supplier portal','become a supplier']
        if any(n in c for n in neutral) and not any(s in c for s in strong):
            return False
        return any(s in c for s in strong)
    if 'generic environmental' in t:
        # Generic EmpCo trigger must be an actual external-facing generic claim, not just
        # the word sustainability in a report/menu label.
        generic_claims=['eco-friendly','environmentally friendly','planet friendly','better for the planet','good for the planet','climate friendly','green product','green choice','eco choice','sustainable product','sustainable choice','100% sustainable','fully sustainable']
        return any(x in c for x in generic_claims)
    if 'label' in t or 'certification' in t or 'visual' in t:
        return any(x in c for x in ['label','badge','certified','certification','ecolabel','eco label','green certified','planet approved','leaf','icon','trust mark'])
    if 'future' in t:
        return any(x in c for x in ['net zero','carbon neutral','climate positive','by 2030','by 2040','by 2050','implementation plan','transition plan','climate roadmap'])
    return True



def has_regulatory_green_signal(findings, audience):
    aud=(audience or {}).get('audience','').lower()
    consumer=('client-facing' in aud or 'consumer-facing' in aud or 'commercial' in aud or 'mixed' in aud)
    if not consumer:
        return False
    for f in findings or []:
        if is_placeholder_finding(f.get('type','')):
            continue
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('regulatory_signal','')).lower()
        if any(x in t for x in ['generic environmental','climate-neutrality','offsetting','comparative environmental','future environmental','sustainability label','absolute or purity','legal requirement']):
            return True
    return False

def has_forced_labour_regulatory_signal(findings):
    for f in findings or []:
        if is_placeholder_finding(f.get('type','')):
            continue
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('analysis','')).lower()
        if any(x in t for x in ['forced labour','forced-labour','forced labor','modern slavery','child labour','child labor','traceability','import controls','supplier traceability']):
            return True
    return False

# Stricter negative-stakeholder source filters: company-owned documents, positive news,
# awards, partnerships and neutral corporate announcements are never retained.


def green_negative_compact_sources(results, limit=5):
    return compact_sources([r for r in results if is_green_negative_source(r)], limit)

# Override v26 endpoint implementation with v27 implementation.
def analyse_url(raw):
    return analyse_url_v27(raw)


# -----------------------------
# V54 material problematic claim engine and conservative scoring
# -----------------------------
# This override restores the scan's core objective: detect material problematic
# sustainability claims, especially EmpCo-sensitive wording and forced-labour / supplier
# assurance claims, without treating neutral references as risks.
GENERIC_GREEN_TERMS = [
    'eco-friendly','environmentally friendly','environmentally responsible','planet friendly',
    'better for the planet','good for the planet','ecological','climate friendly','climate-friendly',
    'green','eco','sustainable','natural','biobased','bio-based'
]
GENERIC_GREEN_CONTEXT = [
    'product','products','packaging','collection','range','choice','solution','solutions','material','materials',
    'service','services','brand','offer','offers','made','designed','shop','buy','consumer','customers','item','items'
]
GENERIC_GREEN_EXCLUSIONS = [
    'sustainability report','sustainability strategy','sustainability statement','sustainability policy',
    'sustainability page','sustainability committee','sustainability team','sustainability governance',
    'sustainability targets','sustainability goals','sustainability programme','sustainability program',
    'annual report','esg report','csrd','download','privacy policy','terms of use','cookie'
]

def _material_findings(findings):
    return [f for f in (findings or []) if not is_placeholder_finding(f.get('type',''))]


def _looks_like_generic_green_claim(excerpt, trigger):
    c=(excerpt or '').lower()
    trig=(trigger or '').lower()
    if len(c.strip()) < 18:
        return False
    if any(x in c for x in GENERIC_GREEN_EXCLUSIONS):
        return False
    # Do not retain isolated sustainability navigation/reporting context.
    if trig in ['sustainable','green','eco','natural'] and not any(ctx in c for ctx in GENERIC_GREEN_CONTEXT):
        return False
    # Avoid retaining fragments that merely list a menu category.
    if len(c.split()) <= 6 and not any(ctx in c for ctx in ['product','packaging','choice','range','material','solution']):
        return False
    return True

def _looks_like_future_environmental_claim(excerpt):
    c=(excerpt or '').lower()
    if any(x in c for x in ['net zero by','carbon neutral by','climate neutral by','climate positive by','we will be net zero','we aim to be net zero','committed to net zero','towards net zero']):
        return True
    # Avoid generic sustainability ambition unless it is actually climate/environmental and time-bound.
    return bool(re.search(r'\b(20[3-5]0)\b', c) and any(x in c for x in ['net zero','carbon neutral','climate neutral','emissions','decarbon']))

# v56: social-claim analogue of _looks_like_future_environmental_claim / 'Future
# environmental-performance claim'. Prompted by KU Leuven/HIVA research (2026, fashion
# sector) finding that vague, forward-looking wording on wages, human rights and working
# conditions -- "working towards a foundation for living wages", "wish to build a world
# where human rights are respected" -- was the single largest driver of social-washing risk
# (found in the majority of high-risk social claims), distinct from and not covered by the
# existing absolute/assurance-style triggers in CLAIMS (e.g. "100% of suppliers", "zero
# accidents"). Ambition-only wording with no achieved-outcome, baseline or timeline is the
# pattern to catch here -- companies are not penalised for stating a goal, but for stating it
# in a way that reads as reassurance without being falsifiable or evidenced.
_ASPIRATIONAL_SOCIAL_VERBS=['working towards','working to build','work towards','wish to build','wishes to build',
    'want to build','aim to build','aims to build','aim to create','aims to create','strive to build',
    'strives to build','strive to create','strives to create','ambition to build','our ambition is',
    'committed to building','committed to build','building a foundation','building a basis',
    'envision a world','envisage a world','vision of a world','working towards a world','working towards a future',
    'we believe in a world where','we dream of a world where','on a journey towards','on our journey towards',
    # v85: bare "committed to X" (not just "committed to BUILDING X") is the far more common
    # real-world phrasing of the exact same ambition-only pattern this function targets --
    # "We are committed to fair working conditions for all workers in our supply chain" has no
    # achieved-outcome, baseline or timeline either, but the verb list only caught the narrower
    # "committed to building" form. Still gated on a nearby social topic below, same as every
    # other verb here, so this doesn't fire on unrelated commitments ("committed to quarterly
    # board meetings").
    'committed to','commitment to','committed to ensuring','committed to promoting','committed to protecting',
    'committed to upholding','committed to respecting',
    'werken aan','werken naar','werken aan de opbouw van','willen bouwen aan','streven naar','we streven ernaar',
    'onze ambitie is','toegewijd aan het opbouwen van','op weg naar','we geloven in een wereld waarin',
    'we dromen van een wereld waarin','onderweg naar','op onze weg naar','toegewijd aan','we zetten ons in voor',
    'nous travaillons vers','nous travaillons à construire','nous visons à construire','nous voulons construire',
    'notre ambition est','engagés à construire','nous croyons en un monde où','nous rêvons d\'un monde où',
    'en chemin vers','sur notre chemin vers','nous aspirons à','engagés à','engagée à',"nous nous engageons à"]
_SOCIAL_ASPIRATION_TOPICS=['living wage','living wages','human rights','fair wage','fair wages','decent work',
    'decent working conditions','good working conditions','safe working conditions','working conditions',
    'workers rights',"workers' rights",
    'worker rights','labour rights','labor rights','gender equality','equal opportunities','dignity',
    'respected','well-being of workers','wellbeing of workers','fair treatment','social justice','worker welfare',
    'workers welfare',
    'leefbaar loon','mensenrechten','eerlijk loon','waardig werk','goede arbeidsomstandigheden',
    'veilige arbeidsomstandigheden','arbeidsomstandigheden','rechten van werknemers','arbeidsrechten','gendergelijkheid','gelijke kansen',
    'waardigheid','gerespecteerd','welzijn van werknemers','eerlijke behandeling','sociale rechtvaardigheid',
    'werknemerswelzijn',
    'salaire vital','droits humains','salaire équitable','travail décent','bonnes conditions de travail',
    'conditions de travail sûres','conditions de travail','droits des travailleurs','droits du travail','égalité des genres',
    'égalité des chances','dignité','respecté','bien-être des travailleurs','traitement équitable',
    'justice sociale']

_SOCIAL_PROCESS_EVIDENCE_TERMS=['due diligence','grievance mechanism','grievance channel','grievance procedure',
    'independently audited','third-party audit','third party audit','regularly audited','externally verified',
    'zorgvuldigheidsplicht','klachtenmechanisme','klachtenprocedure','onafhankelijk gecontroleerd','extern geverifieerd',
    'devoir de vigilance','mécanisme de plainte','procédure de plainte','audité de manière indépendante','vérifié de manière externe']

def _looks_like_aspirational_social_claim(excerpt):
    c=(excerpt or '').lower()
    if not any(v in c for v in _ASPIRATIONAL_SOCIAL_VERBS):
        return False
    if not any(t in c for t in _SOCIAL_ASPIRATION_TOPICS):
        return False
    # v86: a commitment paired with concrete process evidence in the same passage ("We are
    # committed to respecting human rights... We conduct due diligence and maintain grievance
    # mechanisms") is a substantiated policy statement, not the empty, unfalsifiable ambition
    # wording this function exists to catch -- the whole point of "aspirational" flagging is
    # the ABSENCE of exactly this kind of evidence. Flagging it as High regardless of the
    # evidence right next to it over-penalised ordinary, reasonably well-evidenced policy
    # commitments.
    if any(t in c for t in _SOCIAL_PROCESS_EVIDENCE_TERMS):
        return False
    return True

def _social_claim_context(excerpt, typ, trigger, full_text=None):
    c=_normalize_apostrophes((excerpt or '').lower()); t=(typ or '').lower(); trig=(trigger or '').lower()
    if len(c.strip()) < 35:
        return False
    neutral_supplier_phrases=['backing british suppliers','supporting local suppliers','working with suppliers','our suppliers include','supplier list','become a supplier','contact suppliers','supplier portal',
        'lokale leveranciers ondersteunen','samenwerken met leveranciers','onze leveranciers omvatten','leverancierslijst','leverancier worden','contacteer leveranciers','leveranciersportaal',
        'soutenir les fournisseurs locaux','travailler avec des fournisseurs','nos fournisseurs comprennent','liste des fournisseurs','devenir fournisseur','contacter les fournisseurs','portail fournisseurs']
    if any(p in c for p in neutral_supplier_phrases):
        # Keep only if the same passage also contains a clear assurance/control signal.
        strong=['audited','certified','compliant','comply','traceable','ethical sourcing','responsible sourcing','forced labour','forced labor','human rights','due diligence','modern slavery',
            'geauditeerd','gecertificeerd','conform','voldoen','traceerbaar','ethische inkoop','verantwoorde inkoop','dwangarbeid','mensenrechten','zorgvuldigheidsplicht','moderne slavernij',
            'audité','certifié','conforme','se conformer','traçable','approvisionnement éthique','approvisionnement responsable','travail forcé','droits humains','devoir de vigilance','esclavage moderne']
        if not any(s in c for s in strong):
            return False
    if 'supplier' in t or 'supply-chain' in t or 'sourcing' in t:
        # "We ASK all our suppliers to sign our code / share theirs" is a modest governance
        # request, not an assurance that suppliers actually comply -- distinguish it from
        # "all suppliers ARE audited/certified/compliant" style completed-state wording, which
        # is what actually creates a misleading-coverage risk. A bare "all suppliers" substring
        # match caught both equally before this check.
        request_language=['ask all our suppliers','ask our suppliers','we ask suppliers','request suppliers','encourage suppliers','invite suppliers','suppliers to sign','suppliers to share','share theirs with us',
            'vragen al onze leveranciers','vragen onze leveranciers','wij vragen leveranciers','verzoeken leveranciers','moedigen leveranciers aan','nodigen leveranciers uit','leveranciers om te tekenen',
            'demandons à tous nos fournisseurs','demandons à nos fournisseurs','nous demandons aux fournisseurs','encourageons les fournisseurs','invitons les fournisseurs','fournisseurs à signer']
        if any(r in c for r in request_language):
            completion_signals=['audited','certified','compliant','comply','compliance rate','% of suppliers','verified','signed by','have signed',
                'geauditeerd','gecertificeerd','conform','conformiteitspercentage','geverifieerd','ondertekend door','hebben getekend',
                'audité','certifié','conforme','taux de conformité','vérifié','signé par','ont signé']
            return any(s in c for s in completion_signals)
        strong=['all suppliers','100% of suppliers','audited','certified','compliant','comply','meet our standards','traceable','ethical sourcing','responsible sourcing','due diligence','human rights','forced labour','forced labor','modern slavery','supplier code compliance','tier 1','tier 2',
            'alle leveranciers','100% van de leveranciers','geauditeerd','gecertificeerd','conform','voldoen aan onze normen','traceerbaar','ethische inkoop','verantwoorde inkoop','zorgvuldigheidsplicht','mensenrechten','dwangarbeid','moderne slavernij','naleving leverancierscode',
            'tous les fournisseurs','100% des fournisseurs','audité','certifié','conforme','répond à nos normes','traçable','approvisionnement éthique','approvisionnement responsable','devoir de vigilance','droits humains','travail forcé','esclavage moderne','conformité au code fournisseur']
        return any(s in c for s in strong)
    if 'aspirational' in t or ('future' in t and 'social' in t):
        # v86: _v55_sentence_list() only extracts the ONE sentence containing the trigger, so
        # process-evidence wording in the very next sentence ("We are committed to respecting
        # human rights across our operations. We conduct due diligence and maintain grievance
        # mechanisms.") was invisible to _looks_like_aspirational_social_claim's evidence
        # exception -- the check never saw it. Widen the window (evidence-check only, not the
        # excerpt shown to the reviewer) to include a bit of text right after the trigger.
        wider=c
        if full_text:
            low_full=_normalize_apostrophes((full_text or '').lower())
            pos=low_full.find(trig)
            if pos!=-1:
                # v87: a flat 250-char span can cross from the commitment sentence into an
                # UNRELATED topic and still count as "evidence" -- reproduced with "We are
                # committed to respecting human rights... Separately, our annual financial
                # statements were subject to statutory audit and due diligence procedures
                # required by law." ("due diligence"/"audit" here are financial-reporting
                # boilerplate, not human-rights process evidence, yet the flat window still saw
                # them and wrongly excluded a genuinely unsubstantiated claim). Bound the
                # extension to just the ONE immediately-following sentence (matching the
                # original target case), and skip it altogether when that next sentence opens
                # with a topic-shift discourse marker.
                after=low_full[pos+len(trig):pos+len(trig)+250]
                # after[0] is usually still the tail of the TRIGGER's own sentence (e.g. trig=
                # "committed to" matches early, leaving "...respecting human rights..." before
                # the first period) -- split into sentences so the topic-shift check looks at
                # the actual NEXT sentence, not just whatever text precedes the first period.
                sentence_parts=re.split(r'(?<=[.!?])\s+',after)
                include=sentence_parts[:1]
                if len(sentence_parts)>1:
                    next_sentence=sentence_parts[1].strip()
                    topic_shift=['separately','elsewhere','in addition','meanwhile','unrelated','in other news','on a different note','turning to','par ailleurs',"d'autre part",'overigens','daarnaast']
                    if not any(next_sentence.startswith(m) for m in topic_shift):
                        include.append(sentence_parts[1])
                wider=c+' '+' '.join(include)
        return _looks_like_aspirational_social_claim(wider)
    if 'forced' in t:
        return any(s in c for s in ['forced labour','forced labor','modern slavery','child labour','child labor','traceability','import controls','product traceability','supplier traceability',
            'dwangarbeid','moderne slavernij','kinderarbeid','traceerbaarheid','importcontroles','producttraceerbaarheid','traceerbaarheid van leveranciers',
            'travail forcé','esclavage moderne',"travail des enfants",'traçabilité',"contrôles à l'importation",'traçabilité des produits','traçabilité des fournisseurs'])
    if 'human-rights' in t or 'labour-rights' in t or 'labor-rights' in t:
        return any(s in c for s in ['human rights','labour rights','labor rights','living wage','decent work','fair wages','worker rights','no discrimination','zero discrimination','equal pay',
            'mensenrechten','arbeidsrechten','leefbaar loon','waardig werk','eerlijke lonen','rechten van werknemers','geen discriminatie','nul discriminatie','gelijke beloning',
            'droits humains','droits du travail','salaire vital','travail décent','salaires équitables','droits des travailleurs','aucune discrimination','discrimination zéro','égalité salariale'])
    if 'safety' in t:
        return any(s in c for s in ['zero harm','zero accidents','injury free','guaranteed safe','safe workplace guaranteed',
            'nul letsel','nul ongevallen','letselvrij','gegarandeerd veilig','gegarandeerd veilige werkplek',
            'zéro dommage','zéro accident','sans blessure','sécurité garantie','lieu de travail sûr garanti'])
    if 'diversity' in t or 'inclusion' in t:
        return any(s in c for s in ['100% inclusive','fully inclusive','guaranteed equal','no pay gap','zero pay gap','no discrimination','zero discrimination',
            '100% inclusief','volledig inclusief','gegarandeerd gelijk','geen loonkloof','nul loonkloof','geen discriminatie','nul discriminatie',
            '100% inclusif','entièrement inclusif','égalité garantie','aucun écart salarial','écart salarial zéro','aucune discrimination','discrimination zéro'])
    return True

# v73: matches "made with 50% recycled plastic", "contains 30% recycled content", "70% recycled"
# etc. -- an arbitrary percentage can never be listed as a fixed trigger phrase.
_PERCENT_RECYCLED_RE=re.compile(r'\b\d{1,3}\s?%\s+recycled(?:\s+\w+)?\b', re.I)
# NL "gerecycleerd/gerecycled" and FR "recyclé(e)(s)" equivalents of the English pattern above --
# same arbitrary-percentage problem, so a fixed trigger phrase can never cover these either.
# NL/FR word order routinely separates the percentage from the recycled-word with an
# intervening noun ("gemaakt van plastic met 60% gerecycled inhoud" is rare; "60% gerecycled
# plastic" and, especially in French, "60% de plastique recyclé" / "recyclé à 60%" are the
# common real-world forms) -- cover the adjacent, "de <noun>"-infixed and reversed patterns.
_PERCENT_RECYCLED_NL_RE=re.compile(r'\b\d{1,3}\s?%\s+(?:\w+\s+)?gerecycle(?:e)?rd[e]?\b|\bgerecycle(?:e)?rd[e]?\s+voor\s+\d{1,3}\s?%', re.I)
_PERCENT_RECYCLED_FR_RE=re.compile(r'\b\d{1,3}\s?%\s+(?:de\s+\w+\s+)?recycl[ée]e?s?\b|\brecycl[ée]e?s?\s+à\s+\d{1,3}\s?%', re.I)

# Better-balanced green claim taxonomy: includes plural/common variants while retaining only claim-like contexts.
GREEN_CLAIMS=[
 (['eco-friendly','environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','ecological','climate friendly','climate-friendly','green product','green products','green choice','eco choice','eco product','eco products','sustainable product','sustainable products','sustainable choice','sustainable collection','sustainable range','sustainable materials','100% sustainable','fully sustainable','natural product','natural products','biobased product','bio-based product',
   'milieuvriendelijk','milieuvriendelijke','ecologisch','ecologische','klimaatvriendelijk','klimaatvriendelijke','beter voor het milieu','beter voor de planeet','goed voor het milieu','goed voor de planeet','groen product','groene producten','groene keuze','eco product','eco producten','duurzaam product','duurzame producten','duurzame keuze','duurzame collectie','duurzaam assortiment','duurzame materialen','100% duurzaam','volledig duurzaam','natuurlijk product','natuurlijke producten','biogebaseerd product',
   "respectueux de l'environnement","respectueuse de l'environnement",'écologique','écologiques','respectueux du climat','meilleur pour la planète','bon pour la planète','produit vert','produits verts','choix vert','choix écologique','produit écologique','produits écologiques','produit durable','produits durables','choix durable','collection durable','gamme durable','matériaux durables','100% durable','entièrement durable','produit naturel','produits naturels','produit biosourcé'],'Generic environmental claim','High','EmpCo risk: generic environmental claims can be prohibited in consumer-facing communication where the claim is not clearly and prominently specified on the same medium or backed by recognised excellent environmental performance relevant to the claim as a whole.','Replace generic wording with a precise, evidence-backed claim stating the exact product attribute, scope, geography, methodology, period and limitations.'),
 (['carbon neutral','climate neutral','co2 neutral','co₂ neutral','net zero product','carbon negative','carbon positive','climate positive','carbon compensated','climate compensated','offset-based','offsetting','compensated emissions','reduced climate impact',
   'klimaatneutraal','koolstofneutraal','co2-neutraal','co₂-neutraal','netto nul product','klimaatpositief','koolstofpositief','klimaatgecompenseerd','koolstofgecompenseerd','gecompenseerde emissies','gecompenseerde uitstoot','verminderde klimaatimpact','emissiecompensatie',
   'neutre en carbone','carboneutre','neutralité carbone','co2 neutre','co₂ neutre','net zéro produit','climat positif','carbone positif','émissions compensées','compensation carbone','impact climatique réduit'],'Climate-neutrality or offsetting claim','High','EmpCo risk: product-level claims that state or imply neutral, reduced or positive climate impact based on greenhouse-gas offsetting are high-priority blacklisted-practice indicators.','Avoid product-level neutrality wording based on offsets. Separate actual emissions reductions from offsets and disclose scopes, baseline, methodology, residual emissions and progress.'),
 (['greener than','more sustainable than','more eco-friendly than','lower impact than','lowest emissions','best environmental','less harmful than','lower emissions than','reduced emissions compared','reduced impact compared','lower carbon than','less carbon than',
   'groener dan','duurzamer dan','milieuvriendelijker dan','lagere impact dan','laagste uitstoot','beste voor het milieu','minder schadelijk dan','lagere emissies dan','verminderde uitstoot vergeleken','lagere koolstofuitstoot dan','minder koolstof dan',
   'plus vert que','plus durable que','plus écologique que','impact plus faible que','émissions les plus faibles','meilleur pour l\'environnement','moins nocif que','émissions inférieures à','impact réduit par rapport à','moins de carbone que'],'Comparative environmental claim','High','EmpCo risk: environmental comparisons require information on the comparison method, comparator, products and suppliers compared, data sources and update process.','State the comparator, baseline, methodology, scope, data date and update mechanism; avoid vague superiority claims.'),
 (['eco label','ecolabel','sustainability label','self-declared sustainability label','green certified','eco certified','planet approved','responsible choice label','green badge','eco badge','sustainability badge','certified sustainable','sustainably certified',
   'ecolabel','duurzaamheidslabel','zelfverklaard duurzaamheidslabel','groen gecertificeerd','eco-gecertificeerd','verantwoorde keuze label','groen keurmerk','eco-keurmerk','duurzaamheidskeurmerk','gecertificeerd duurzaam','duurzaam gecertificeerd',
   'écolabel','label de durabilité','label autodéclaré','certifié vert','certifié écologique','label de choix responsable','badge vert','badge écologique','certifié durable'],'Sustainability label / certification claim','High','EmpCo risk: self-declared sustainability labels are blacklisted unless based on an independent, transparent certification scheme or public-authority label. Icons, symbols and trust marks may fall within this category.','Name the scheme owner, criteria, independence, audit basis, scope and validity period. Remove self-declared labels or clarify them as non-certification claims.'),
 (['we will be net zero','we aim to be net zero','we are working towards net zero','committed to net zero','net zero by 2030','net zero by 2040','net zero by 2050','climate positive by','carbon neutral by','climate neutral by','decarbonisation roadmap','decarbonization roadmap',
   'we zullen netto nul zijn','we willen netto nul bereiken','we werken aan netto nul','toegewijd aan netto nul','netto nul tegen 2030','netto nul tegen 2040','netto nul tegen 2050','klimaatpositief tegen','klimaatneutraal tegen','koolstofneutraal tegen','decarbonisatietraject','routekaart naar decarbonisatie',
   'nous serons neutres en carbone','nous visons la neutralité carbone','nous travaillons vers le zéro net','engagés vers le zéro net','zéro net d\'ici 2030','zéro net d\'ici 2040','zéro net d\'ici 2050','climat positif d\'ici','neutre en carbone d\'ici','feuille de route de décarbonation'],'Future environmental-performance claim','High','EmpCo risk: future environmental-performance claims require clear, objective, publicly available and verifiable commitments supported by a realistic implementation plan.','Add a public implementation plan, milestones, resources, governance, progress indicators, verification basis and scope limitations.'),
 (['all natural','100% natural','chemical free','zero impact','no impact','zero waste','waste free','pollution free','fully recyclable','100% recyclable','completely biodegradable','fully biodegradable','plastic free','100% recycled',
   'volledig natuurlijk','100% natuurlijk','chemievrij','geen impact','nul impact','zero waste','afvalvrij','vervuilingsvrij','volledig recyclebaar','100% recyclebaar','volledig biologisch afbreekbaar','plasticvrij','100% gerecycleerd','100% gerecycled',
   'tout naturel','100% naturel','sans produits chimiques','aucun impact','impact zéro','zéro déchet','sans déchets','sans pollution','entièrement recyclable','100% recyclable','entièrement biodégradable','sans plastique','100% recyclé'],'Absolute or purity environmental wording','High','EmpCo risk: absolute environmental wording creates a high evidence burden and can mislead when scope, conditions or limitations are missing.','Qualify the claim and specify exact attribute, scope, conditions, test method, limitations and evidence.'),
 (['compliant with environmental law','meets legal requirements','according to legal standards','required by law','legal requirement','eu compliant','regulation compliant',
   'conform milieuwetgeving','voldoet aan wettelijke vereisten','volgens wettelijke normen','wettelijk verplicht','wettelijke vereiste','eu-conform','conform de regelgeving',
   'conforme à la législation environnementale','répond aux exigences légales','selon les normes légales','requis par la loi','exigence légale','conforme ue','conforme à la réglementation'],'Legal requirement presented as green benefit','High','EmpCo risk: presenting requirements imposed by law as a distinctive environmental feature is a blacklisted-practice indicator.','Do not present legal compliance as a differentiating sustainability benefit. Separate legal compliance from voluntary improvements.'),
 (['green leaf','leaf icon','tree icon','water drop','waterdrop','planet icon','earth icon','eco badge','green badge','environmental icon','recycled badge','sustainability badge',
   'groen blad','blad icoon','boom icoon','waterdruppel','planeet icoon','aarde icoon','milieu icoon','recyclagebadge','duurzaamheidsbadge',
   'feuille verte',"icône feuille","icône arbre","goutte d'eau","icône planète","icône terre","icône environnement","badge recyclage","badge durabilité"],'Visual green-claim indicator','Medium','EmpCo risk: pictorial, graphic or symbolic representations can imply environmental benefits and should be assessed like written claims.','Check whether the icon or badge implies a specific environmental benefit and connect it to clear, prominent and evidenced wording.'),
]

CLAIMS=[
 (['forced labour free','forced labor free','free from forced labour','free from forced labor','no forced labour','no forced labor','modern slavery free','child labour free','child labor free','no child labour','no child labor','forced labour due diligence','forced labor due diligence','product traceability','supplier traceability','import controls',
   'vrij van dwangarbeid','geen dwangarbeid','vrij van moderne slavernij','vrij van kinderarbeid','geen kinderarbeid','zorgvuldigheidsplicht dwangarbeid','producttraceerbaarheid','traceerbaarheid van leveranciers','importcontroles',
   'sans travail forcé',"exempt de travail forcé",'aucun travail forcé','sans esclavage moderne','sans travail des enfants',"aucun travail des enfants",'devoir de vigilance travail forcé','traçabilité des produits','traçabilité des fournisseurs',"contrôles à l'importation"],'Forced-labour product or supply-chain claim','High','Forced Labour Regulation risk: the wording may imply product, supplier or supply-chain assurance against forced labour. Such claims require strong traceability, risk assessment, mitigation, remediation and withdrawal/customs response readiness.','Scope the wording and disclose a risk-based due-diligence process, product/supplier traceability, escalation and remediation steps.'),
 (['all suppliers audited','all suppliers are audited','all suppliers certified','all suppliers are certified','all suppliers comply','all suppliers are compliant','all suppliers meet','100% of suppliers','fully traceable supply chain','fully audited supply chain','ethical sourcing','responsible sourcing','responsibly sourced','responsibly-sourced','ethically sourced','certified suppliers','audited suppliers','traceable suppliers','supplier code compliance','certified against our supplier code','comply with our supplier code',
   'alle leveranciers geauditeerd','alle leveranciers zijn geauditeerd','alle leveranciers gecertificeerd','alle leveranciers zijn gecertificeerd','alle leveranciers voldoen','100% van de leveranciers','volledig traceerbare toeleveringsketen','volledig geauditeerde toeleveringsketen','ethische inkoop','verantwoorde inkoop','verantwoord ingekocht','ethisch ingekocht','gecertificeerde leveranciers','geauditeerde leveranciers','traceerbare leveranciers','naleving leverancierscode',
   'leveranciers worden geauditeerd','leveranciers worden gecontroleerd','leveranciers worden gecertificeerd','onze leveranciers worden jaarlijks geauditeerd','onze leveranciers worden regelmatig geauditeerd',
   'tous les fournisseurs audités','tous nos fournisseurs sont audités','tous les fournisseurs certifiés','tous nos fournisseurs sont certifiés','tous les fournisseurs sont conformes','100% des fournisseurs','chaîne d\'approvisionnement entièrement traçable','chaîne d\'approvisionnement entièrement auditée','approvisionnement éthique','approvisionnement responsable','sourcing responsable','fournisseurs certifiés','fournisseurs audités','fournisseurs traçables','conformité au code fournisseur',
   'fournisseurs sont audités','fournisseurs sont contrôlés','fournisseurs sont certifiés','nos fournisseurs sont audités chaque année','nos fournisseurs sont contrôlés chaque année'],'Supply-chain or supplier-responsibility claim','High','The wording may imply broad supplier control or responsible value-chain coverage. It is problematic where supplier tiers, audit quality, worker voice, findings and remediation are not clear.','Scope the claim to covered supplier tiers and disclose coverage, methodology, findings and corrective-action closure rates.'),
 (['human rights compliant','respect human rights across our value chain','protect human rights across our value chain','respect human rights in our supply chain','living wage across our supply chain','decent work guaranteed','guaranteed labour rights','guaranteed labor rights','fair wages across our supply chain','no discrimination','zero discrimination','equal pay guaranteed',
   'conform mensenrechten','respecteren mensenrechten in onze waardeketen','beschermen mensenrechten in onze waardeketen','respecteren mensenrechten in onze toeleveringsketen','leefbaar loon in onze toeleveringsketen','gegarandeerd waardig werk','gegarandeerde arbeidsrechten','eerlijke lonen in onze toeleveringsketen','geen discriminatie','nul discriminatie','gegarandeerde gelijke beloning',
   'wij respecteren de mensenrechten','we respecteren de mensenrechten','wij beschermen de mensenrechten','we beschermen de mensenrechten','wij garanderen eerlijke lonen','we garanderen eerlijke lonen',
   'conforme aux droits humains','respect des droits humains dans notre chaîne de valeur','protection des droits humains dans notre chaîne de valeur','respect des droits humains dans notre chaîne d\'approvisionnement','salaire vital dans notre chaîne d\'approvisionnement','travail décent garanti','droits du travail garantis','salaires équitables dans notre chaîne d\'approvisionnement','aucune discrimination','discrimination zéro','égalité salariale garantie',
   'nous respectons les droits humains','nous protégeons les droits humains','nous garantissons des salaires équitables','nous garantissons un travail décent'],'Human-rights or labour-rights claim','High','The claim refers to sensitive rights topics and may overstate outcomes or control without due diligence, grievance channels, tracking and remedy.','State the due-diligence process, salient risks, coverage, grievance channels, tracking, limits and remediation process.'),
 (['safe workplace guaranteed','zero accidents','zero harm','injury free','guaranteed safe workplace','no workplace injuries',
   'gegarandeerd veilige werkplek','nul ongevallen','geen letsel','letselvrij','geen arbeidsongevallen',
   'lieu de travail sûr garanti','zéro accident','zéro blessure','sans blessure','aucun accident du travail'],'Health, safety or worker-welfare claim','High','Absolute safety or welfare wording creates a high evidence burden and can overstate outcomes, particularly where contractors or suppliers are involved.','Use scoped wording linked to incident data, controls, coverage, training and corrective actions.'),
 (['all employees included','fully inclusive workplace','100% inclusive','guaranteed equal opportunities','no pay gap','zero pay gap',
   'alle werknemers inbegrepen','volledig inclusieve werkplek','100% inclusief','gegarandeerde gelijke kansen','geen loonkloof','nul loonkloof',
   'tous les employés inclus','lieu de travail entièrement inclusif','100% inclusif','égalité des chances garantie','aucun écart salarial','écart salarial zéro'],'Diversity, equality and inclusion claim','Medium','Absolute inclusion, equality or pay-gap wording may overstate outcomes unless backed by data, scope, baseline and progress evidence.','Add workforce data, baseline, scope, limitations, methodology and progress indicators.'),
 (_ASPIRATIONAL_SOCIAL_VERBS,'Aspirational or future social-performance claim','High','The wording describes an ambition or ongoing effort ("working towards", "wish to build a world where") rather than an achieved, current-state outcome. Aspirational, forward-looking commitments on wages, human rights or working conditions are treated as a relevant social-washing risk indicator whenever no baseline, timeline or achieved result is given -- not as evidence of a specific academic finding about how common or dominant this pattern is in any sector.','State what has actually been achieved to date and on what evidence basis, and give a specific timeline and measurable target for the remaining ambition. Do not present an ongoing effort as if it were a current outcome.'),
]





def _v86_claim_local_text(findings, page_segments, full_text):
    """Scope evidence-term matching to the page(s) that actually contain a material claim,
    instead of the entire crawled corpus. Falls back to the full corpus when no page-segment
    link is available (e.g. a single uploaded document, or a claim whose source page could not
    be matched to a segment) -- this preserves existing behaviour for those cases rather than
    silently returning a thin/empty result.

    v86: evidence_signal_score()/green_evidence_signal_score() searched the entire crawled
    corpus for evidence terms with no regard to which page a claim actually came from.
    Reproduced directly: a bare claim ("Our new product is sustainable and better for the
    planet") scored little substantiation alone, but adding "Scope 1", "Scope 2", "baseline",
    "ISO", "verified", "third-party audit" etc. ANYWHERE ELSE on the site measurably reduced
    that claim's evidence gap, even though the evidence has nothing to do with that specific
    product or claim. Restricting the search to the claim's own source page(s) is a real,
    bounded step toward claim-specific evidence matching, using the page-segment/source-url
    infrastructure already built for claim-source attribution elsewhere in this file -- short
    of a full per-sentence-window rewrite, which would need much deeper changes to how excerpts
    are tracked."""
    material=[f for f in findings or [] if not is_placeholder_finding(f.get('type',''))]
    if not page_segments or not material:
        return full_text
    wanted={f.get('source_url') for f in material if f.get('source_url')}
    if not wanted:
        return full_text
    matched_segments=[seg for seg in page_segments if seg.get('url') in wanted]
    # v87: fall back to the full corpus only when NO segment's URL matched at all (genuinely no
    # data to scope to). The previous version instead checked whether the joined LOCAL TEXT was
    # non-empty -- so a claim whose source page matched a real segment that just happened to
    # have empty/unextracted text (e.g. a JS-rendered page parse_html couldn't read) silently
    # fell back to full-corpus behaviour too, reopening exactly the cross-page evidence leakage
    # this function exists to prevent. A matched-but-empty page should stay empty (a real "no
    # local evidence" signal), not be treated the same as "no page-segment data available".
    if not matched_segments:
        return full_text
    local_text='\n'.join(seg.get('text','') for seg in matched_segments if seg.get('text'))
    return local_text


def calc_green_score(findings, sector, ext, page_text, audience, page_segments=None):
    material=_material_findings(findings)
    local_text=_v86_claim_local_text(findings, page_segments, page_text)
    substantiation, evidence_notes=green_evidence_signal_score(local_text, findings)
    external_context=green_external_context_risk(ext)
    external_score=external_context.get('score',0)
    sector_score=sector_environment_score(sector)
    audience_label=audience.get('audience','') if isinstance(audience,dict) else ''
    audience_factor=1.0 if ('Client-facing' in audience_label or 'Consumer-facing' in audience_label or 'commercial' in audience_label.lower()) else 0.90 if ('Mixed' in audience_label or 'unclear' in audience_label.lower()) else 0.75
    regulatory=any(f.get('blacklisted_practice_indicator') for f in material)
    score=_recalibrated_score(material, substantiation, evidence_notes, external_score, sector_score, regulatory, audience_factor)
    top=max([f.get('claim_score',0) for f in material] or [8])
    comps={'claim_wording_risk':min(100, top + 5*(len(material)-1)) if material else 8,'substantiation_risk':15 if not material else max(0,100-substantiation),'external_context_risk':external_score,'sector_baseline_risk':sector_score,'substantiation_score':substantiation,'evidence_notes':evidence_notes,'audience_factor':audience_factor,'score_calculation_note':'Score = 50% claim wording severity + 22% evidence gap + 20% external stakeholder context + 8% sector/channel sensitivity, weighted by audience factor and capped conservatively so that isolated claim signals cannot alone drive a High/Very high result unless they are a direct blacklisted-practice indicator or are supported by negative external stakeholder signals.'}
    return score, comps, external_context

def calc_score(findings,sector,context,external_research=None,page_text="",company_name="",audience=None,page_segments=None):
    material=_material_findings(findings)
    local_text=_v86_claim_local_text(findings, page_segments, page_text)
    substantiation, evidence_notes=evidence_signal_score(local_text, findings)
    external_context=strict_external_context_risk(external_research or {}, company_name)
    external_score=external_context.get('score',0)
    sector_score={"Low":10,"Medium":35,"High":60}.get(sector.get("level","Medium"),35)
    regulatory=any(('forced-labour' in f.get('type','').lower() or 'forced labor' in f.get('type','').lower()) for f in material)
    # v86: this always passed a hardcoded 1.0 -- calc_green_score applies an audience_factor
    # (consumer-facing 1.00 / mixed 0.90 / investor-internal 0.75) but calc_score's own
    # signature didn't even accept an audience argument, so an internal governance-document
    # social claim scored the same as the identical wording on a public product page, despite
    # the app's own audience methodology saying internal content should not be weighted like
    # consumer-facing marketing.
    audience_label=audience.get('audience','') if isinstance(audience,dict) else ''
    audience_factor=1.0 if ('Client-facing' in audience_label or 'Consumer-facing' in audience_label or 'commercial' in audience_label.lower()) else 0.90 if ('Mixed' in audience_label or 'unclear' in audience_label.lower()) else 0.75
    score=_recalibrated_score(material, substantiation, evidence_notes, external_score, sector_score, regulatory, audience_factor)
    external_mod, external_note=external_relevance_score(findings, external_research or {})
    top=max([f.get('claim_score',0) for f in material] or [8])
    comps={"claim_wording_risk":min(100, top + 5*(len(material)-1)) if material else 8,"substantiation_risk":15 if not material else max(0,100-substantiation),"external_context_risk":external_score,"sector_baseline_risk":sector_score,"substantiation_score":substantiation,"evidence_notes":evidence_notes,"audience_factor":audience_factor,"score_calculation_note":"Score = 50% claim wording severity + 22% evidence gap + 20% external stakeholder context + 8% sector/channel sensitivity, weighted by audience factor and capped conservatively so that isolated claim signals cannot alone drive a High/Very high result unless they are a direct regulatory (forced-labour) indicator or are supported by negative external stakeholder signals."}
    return score, external_mod, external_note, evidence_quality_credit(local_text, findings), comps

def recalc_global_score(green_score, social_score, green_findings=None, social_findings=None):
    gmat=_material_findings(green_findings); smat=_material_findings(social_findings)
    if not gmat and not smat:
        return round((green_score+social_score)/2)
    # Green and social are independent; global reflects the stronger dimension without becoming identical by default.
    stronger=max(green_score, social_score); weaker=min(green_score, social_score)
    return round(stronger*0.70 + weaker*0.30)


# Exact passage extraction for displayed claim signals. Unlike the generic excerpt helper, this
# does not expand short sentences into neighbouring text, so the report shows where the claim actually stands.
def _near_sentence(text, trigger, max_len=620):
    text=text or ''; trig=trigger or ''
    if not trig: return text[:min(len(text),max_len)]
    low=text.lower(); i=low.find(trig.lower())
    if i<0: return text[:min(len(text),max_len)]
    # Prefer sentence-level extraction. Include common bullet and line delimiters.
    start_candidates=[text.rfind('.',0,i), text.rfind('\n',0,i), text.rfind('•',0,i), text.rfind(';',0,i)]
    s=max(start_candidates); s=0 if s<0 else s+1
    end_candidates=[p for p in [text.find('.',i+len(trig)), text.find('\n',i+len(trig)), text.find('•',i+len(trig)), text.find(';',i+len(trig))] if p!=-1]
    e=(min(end_candidates)+1) if end_candidates else min(len(text), i+len(trig)+220)
    out=' '.join(text[s:e].split()).strip()
    if not out:
        out=' '.join(text[max(0,i-80):min(len(text),i+len(trig)+160)].split()).strip()
    return out[:max_len]+('...' if len(out)>max_len else '')

def _client_ip(handler):
    # v73: use the LAST hop in X-Forwarded-For, not the first. On a single-proxy platform
    # (Render), the last entry is the one the platform's own edge proxy appended and is not
    # attacker-controlled; a client can freely forge earlier entries in its own request headers,
    # which previously let a client bypass rate limiting by sending a different fake first IP on
    # every request.
    forwarded=(handler.headers.get('X-Forwarded-For') or '').strip()
    if forwarded:
        parts=[p.strip() for p in forwarded.split(',') if p.strip()]
        if parts:
            return parts[-1]
    return handler.client_address[0] if handler.client_address else 'unknown'


def _rate_limit_allowed(client,bucket,maximum):
    now=time.time(); key=(client,bucket)
    with _RATE_LOCK:
        recent=[t for t in _RATE_EVENTS.get(key,[]) if now-t<RATE_LIMIT_WINDOW_SECONDS]
        if len(recent)>=maximum:
            _RATE_EVENTS[key]=recent; return False
        recent.append(now); _RATE_EVENTS[key]=recent
        # v73: sweep fully-expired keys once the table grows large, so long-running processes
        # with many distinct visitors don't accumulate unbounded empty/stale dict entries.
        if len(_RATE_EVENTS) > 5000:
            for stale_key in [k for k,v in _RATE_EVENTS.items() if not v or now-v[-1]>=RATE_LIMIT_WINDOW_SECONDS]:
                del _RATE_EVENTS[stale_key]
    return True


def _unsigned_report_payload(payload):
    return {k:v for k,v in (payload or {}).items() if k not in {
        '_report_signature','_report_signature_version','_report_token','_report_token_version'
    }}

_EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def is_valid_email(value):
    return bool(_EMAIL_RE.match((value or '').strip())) and len(value or '')<=254

def send_report_pdf_email(to_email,pdf_bytes,company_name,stamp):
    """Email the generated company-report PDF as an attachment via Brevo's transactional-email API.

    Uses HTTPS (Render blocks outbound SMTP ports 25/465/587 on free web services, so raw
    smtplib fails there with "Network is unreachable" regardless of credentials -- HTTPS is
    not affected). Raises RuntimeError with a user-facing message on any failure; never logs
    the recipient address or the message body.
    """
    if not (BREVO_API_KEY and BREVO_SENDER_EMAIL):
        raise RuntimeError('Email delivery is not configured on this deployment (BREVO_API_KEY / BREVO_SENDER_EMAIL missing).')
    who=(company_name or 'Company').strip() or 'Company'
    fname=f'durably_company_report_{stamp}.pdf'
    payload={
        'sender':{'email':BREVO_SENDER_EMAIL,'name':'Durably Sustainability Claims Risk Scan'},
        'to':[{'email':to_email}],
        'subject':f'Durably Sustainability Claims Risk Scan report - {who} - {stamp}',
        'textContent':(
            f'Attached: the Durably Sustainability Claims Risk Scan claim-risk report for {who}, generated {stamp}.\n\n'
            'Indicative first-pass assessment only; results require legal, compliance and subject-matter '
            'review before external use.\n\nDurably - Sustainability Claims Risk Scan'
        ),
        'attachment':[{'content':base64.b64encode(pdf_bytes).decode('ascii'),'name':fname}],
    }
    req=Request('https://api.brevo.com/v3/smtp/email',data=json.dumps(payload).encode(),method='POST',
                headers={'Content-Type':'application/json','Accept':'application/json','api-key':BREVO_API_KEY})
    try:
        with urlopen(req,timeout=20,context=ssl.create_default_context()) as r:
            r.read()
    except HTTPError as e:
        # Brevo's error body (e.g. unverified sender, invalid API key) is safe to surface --
        # it never contains the recipient address or report content.
        try: detail=e.read().decode('utf-8',errors='ignore')[:300]
        except Exception: detail=str(e)
        raise RuntimeError(f'Could not send the report email ({detail}). Please try downloading the PDF instead.') from e
    except Exception as exc:
        raise RuntimeError(f'Could not send the report email ({exc}). Please try downloading the PDF instead.') from exc


def _report_signature(payload):
    """Legacy whole-payload signature retained for backward compatibility.

    Browser JSON round-trips can alter numeric spellings (for example Python 1.0 becomes
    JavaScript 1), so v69 no longer relies on this signature for normal PDF downloads.
    """
    raw=json.dumps(_unsigned_report_payload(payload),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hmac.new(_REPORT_SIGNING_KEY,raw,hashlib.sha256).hexdigest()


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _b64url_decode(value):
    value=str(value or '')
    return base64.urlsafe_b64decode(value+'='*((4-len(value)%4)%4))


def create_report_token(payload):
    """Create an opaque, stateless report token that survives browser JSON parsing.

    The exact server-side scan payload is compressed inside the token. The browser sends
    the token back unchanged; it never has to reproduce the server's JSON number syntax.
    """
    envelope={'issued_at':int(time.time()),'payload':_unsigned_report_payload(payload)}
    raw=json.dumps(envelope,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    body=_b64url_encode(zlib.compress(raw,9))
    signature=hmac.new(_REPORT_SIGNING_KEY,('v1.'+body).encode('ascii'),hashlib.sha256).hexdigest()
    return 'v1.'+body+'.'+signature


def decode_report_token(token):
    try:
        version,body,supplied=str(token or '').split('.',2)
    except ValueError as exc:
        raise ValueError('The report token is malformed. Run a new scan before downloading the report.') from exc
    if version!='v1':
        raise ValueError('The report token version is not supported. Run a new scan before downloading the report.')
    expected=hmac.new(_REPORT_SIGNING_KEY,('v1.'+body).encode('ascii'),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied,expected):
        raise ValueError('The report token is invalid. Run a new scan before downloading the report.')
    try:
        compressed=_b64url_decode(body)
        decomp=zlib.decompressobj()
        raw=decomp.decompress(compressed,MAX_REQUEST_BYTES+1)
        raw+=decomp.flush()
        if len(raw)>MAX_REQUEST_BYTES or decomp.unconsumed_tail:
            raise ValueError('The report token exceeds the application limit.')
        envelope=json.loads(raw.decode('utf-8'))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('The report token could not be decoded. Run a new scan before downloading the report.') from exc
    issued=int(envelope.get('issued_at') or 0)
    if not issued or abs(time.time()-issued)>REPORT_TOKEN_MAX_AGE_SECONDS:
        raise ValueError('The report token has expired. Run a new scan before downloading the report.')
    payload=envelope.get('payload')
    if not isinstance(payload,dict):
        raise ValueError('The report token does not contain a valid scan result.')
    return payload


def attach_report_signature(payload):
    if isinstance(payload,dict):
        # Keep the legacy fields for one-release compatibility, but use the opaque token
        # for the normal browser-to-server PDF workflow.
        payload['_report_signature_version']='hmac-sha256-v1'
        payload['_report_signature']=_report_signature(payload)
        payload['_report_token_version']='compressed-hmac-v1'
        payload['_report_token']=create_report_token(payload)
    return payload


def verify_report_signature(payload):
    supplied=str((payload or {}).get('_report_signature') or '')
    return bool(supplied) and hmac.compare_digest(supplied,_report_signature(payload))


def _v91_4_container_cpu_quota():
    """Best-effort read of the container's actual CPU allocation via the Linux cgroup
    files Render's runtime enforces -- e.g. the free tier's 0.1 CPU vs a paid instance
    type's 0.5/1/2 CPU. This is the only externally-visible signal of the instance's real
    compute tier: Render does not expose plan/instance-type as an env var, and CPU
    throttling from an under-provisioned tier is exactly what was found to be the
    dominant cost of slow PDF extraction/crawling earlier in this investigation, so being
    able to confirm a paid-plan upgrade actually raised the enforced quota (without
    dashboard access) is directly useful, not just diagnostic curiosity.
    Returns None if the cgroup files aren't present (e.g. not running in a Linux
    container, or a cgroup layout this doesn't recognise) rather than guessing.
    """
    try:
        cgroup_v2=Path('/sys/fs/cgroup/cpu.max')
        if cgroup_v2.exists():
            quota_str,period_str=cgroup_v2.read_text().split()
            if quota_str=='max':
                return {'cgroup_version':'v2','cpu_quota':'unlimited'}
            return {'cgroup_version':'v2','allocated_cpus':round(int(quota_str)/int(period_str),3)}
        quota_file=Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
        period_file=Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
        if quota_file.exists() and period_file.exists():
            quota=int(quota_file.read_text().strip()); period=int(period_file.read_text().strip())
            if quota<=0:
                return {'cgroup_version':'v1','cpu_quota':'unlimited'}
            return {'cgroup_version':'v1','allocated_cpus':round(quota/period,3)}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# V92 SCAN HISTORY -- optional Postgres-backed log of past scans, viewable at
# /history behind a single shared password. Entirely opt-in: with DATABASE_URL
# unset, every function below is a safe no-op and the scan endpoints behave
# exactly as before. See render.yaml for the (unset-by-default) env var keys.
# ---------------------------------------------------------------------------

_V92_TABLE_LOCK=threading.Lock()
_V92_TABLE_READY=False
# v92.1: _v92_save_scan_history() deliberately swallows every exception so a database
# problem can never turn a successful scan into a failed response -- but that also makes
# a silent failure impossible to diagnose from outside (no dashboard/log access). Capture
# the last error here so it can be surfaced via /api/health instead of guessed at.
_V92_LAST_ERROR=None

def _v92_redact_error(text):
    """A database connection error can echo back the DSN it tried to use, which for a
    typical Postgres connection string includes the username and PASSWORD in plain text
    (postgresql://user:pass@host/db) -- /api/health is a public, unauthenticated endpoint,
    so this MUST be stripped before the error is ever stored/exposed there, not just before
    display. Redacts the literal configured DATABASE_URL if present, plus any
    scheme://user:pass@ credential pattern in general as defense-in-depth against the
    driver rendering the DSN differently than the exact configured string."""
    text=str(text or '')
    if DATABASE_URL:
        text=text.replace(DATABASE_URL,'[REDACTED]')
    text=re.sub(r'[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@]+@','[REDACTED]://',text)
    return text[:300]

def _v92_db_connect():
    """Returns a new connection, or None if the feature isn't configured/available.
    connect_timeout is deliberately generous (15s, not a couple of seconds) because a
    free-tier serverless Postgres project (e.g. Neon) can scale its compute to zero after
    inactivity and take a few seconds to wake on the first connection after a while --
    a too-short timeout would misreport a cold-start delay as a real connection failure."""
    global _V92_LAST_ERROR
    if not DATABASE_URL:
        return None
    pg=_get_psycopg()
    if pg is None:
        _V92_LAST_ERROR='psycopg not available: '+str(_psycopg_import_error)
        return None
    try:
        return pg.connect(DATABASE_URL,connect_timeout=15)
    except Exception as e:
        _V92_LAST_ERROR=_v92_redact_error('connect failed: '+str(e))
        return None

def _v92_ensure_table(conn):
    global _V92_TABLE_READY,_V92_LAST_ERROR
    if _V92_TABLE_READY:
        return True
    with _V92_TABLE_LOCK:
        if _V92_TABLE_READY:
            return True
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS scan_history (
                        id SERIAL PRIMARY KEY,
                        scanned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        scan_type TEXT,
                        company TEXT,
                        sector TEXT,
                        input_url TEXT,
                        global_score INTEGER,
                        global_risk TEXT,
                        green_score INTEGER,
                        green_risk TEXT,
                        social_score INTEGER,
                        social_risk TEXT,
                        audience TEXT,
                        findings_count INTEGER,
                        summary TEXT,
                        client_ip TEXT
                    )
                ''')
                cur.execute('CREATE INDEX IF NOT EXISTS scan_history_scanned_at_idx ON scan_history (scanned_at DESC)')
                # v92.3: additive migration for a table that may already exist from before
                # this round -- ADD COLUMN IF NOT EXISTS never touches/loses rows already
                # saved (e.g. the KBC scan logged under v92.2), it only widens the schema.
                # Captures more of what a scan already computes, per the user's explicit
                # goal of collecting as much structured, later-filterable/exportable data
                # per scan as reasonably possible (short of the full raw result payload,
                # which would defeat "structured" and bloat a free-tier database for little
                # benefit over what's summarised here).
                for col_sql in (
                    'sector_risk TEXT','data_reliability_warning BOOLEAN',
                    'empco_blacklisted_count INTEGER','high_risk_findings_count INTEGER',
                    'external_green_retained_count INTEGER','external_social_retained_count INTEGER',
                    'document_type TEXT'):
                    cur.execute(f'ALTER TABLE scan_history ADD COLUMN IF NOT EXISTS {col_sql}')
            conn.commit()
            _V92_TABLE_READY=True
            return True
        except Exception as e:
            _V92_LAST_ERROR=_v92_redact_error('ensure_table failed: '+str(e))
            try: conn.rollback()
            except Exception: pass
            return False

def _v92_save_scan_history(result,scan_type,client_ip):
    """Best-effort log of a completed scan. Never raises -- a database problem must
    never turn a successful scan into a failed response for the person using the tool."""
    global _V92_LAST_ERROR
    if not DATABASE_URL:
        return
    try:
        comp=result.get('company') or {}
        # v92.4: infer_company() sets company['sector'] to the literal placeholder
        # "Sector not explicitly identified" for every company outside the ~8-entry
        # hardcoded PROFILES list (KBC, Delhaize, Aldi...) -- Puratos among them -- and
        # company['sector_risk'] stays empty for exactly the same companies. The tool DOES
        # compute a real content-based sector RISK LEVEL (Low/Medium/High) for every scan
        # via the separate infer_sector() function, but that lands in the top-level
        # result['sector'] dict ({'level':...,'basis':...}), not company['sector_risk'] --
        # so the sector_risk column here was silently empty for any company not in that
        # tiny list, even though a real computed value existed. Reported by the user after
        # seeing "Sector not explicitly identified" for Puratos on /history.
        sec=result.get('sector') or {}
        audience=result.get('document_audience') or {}
        findings=result.get('findings') or result.get('merged_claims') or []
        green_findings=result.get('green_findings') or []
        ext=result.get('external_research') or {}
        empco_count=sum(1 for f in green_findings if f.get('blacklisted_practice_indicator'))
        high_risk_count=sum(1 for f in findings if str(f.get('risk','')).lower()=='high')
        green_retained=len((ext.get('green') or {}).get('compact_sources') or [])
        social_retained=len((ext.get('social') or {}).get('compact_sources') or [])
        conn=_v92_db_connect()
        if conn is None:
            return
        try:
            if not _v92_ensure_table(conn):
                return
            with conn.cursor() as cur:
                cur.execute(
                    '''INSERT INTO scan_history
                       (scan_type,company,sector,input_url,global_score,global_risk,
                        green_score,green_risk,social_score,social_risk,audience,
                        findings_count,summary,client_ip,sector_risk,data_reliability_warning,
                        empco_blacklisted_count,high_risk_findings_count,
                        external_green_retained_count,external_social_retained_count,document_type)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (scan_type,
                     str(comp.get('company','') or '')[:300],
                     str(comp.get('sector','') or '')[:300],
                     str(result.get('original_url') or result.get('source_label') or '')[:1000],
                     result.get('global_score'),
                     str(result.get('global_risk','') or '')[:50],
                     result.get('green_score'),
                     str(result.get('green_risk','') or '')[:50],
                     result.get('social_score'),
                     str(result.get('social_risk','') or '')[:50],
                     str(audience.get('audience','') or '')[:200],
                     len(findings),
                     str(result.get('screening_conclusion','') or '')[:2000],
                     str(client_ip or '')[:64],
                     str(sec.get('level','') or comp.get('sector_risk','') or '')[:50],
                     bool(result.get('data_reliability_warning')),
                     empco_count,
                     high_risk_count,
                     green_retained,
                     social_retained,
                     str(result.get('document_type','') or '')[:100]))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        _V92_LAST_ERROR=_v92_redact_error('save failed: '+str(e))

_V92_RISK_LEVELS=('Low','Medium','High','Very high')
_V92_PERIOD_SQL={'month':"date_trunc('month', scanned_at) = date_trunc('month', now())",
                  '30d':"scanned_at >= now() - interval '30 days'",
                  '90d':"scanned_at >= now() - interval '90 days'"}
_V92_EXPORT_COLUMNS=['scanned_at','scan_type','company','sector','sector_risk','input_url',
    'global_score','global_risk','green_score','green_risk','social_score','social_risk',
    'audience','document_type','findings_count','empco_blacklisted_count',
    'high_risk_findings_count','external_green_retained_count','external_social_retained_count',
    'data_reliability_warning','summary']

def _v92_build_filters(search='',risk='',period='',ids=None):
    """Shared WHERE-clause builder for the table view, the stats block and CSV export, so
    all three always agree on what "the current view" means. Every value is bound as a
    parameter, never interpolated into the SQL text, regardless of source.
    v92.6: ids lets "View selected"/"Export selected" narrow to an explicit set of row
    ids (from the /history checkboxes) -- passed as a single list parameter bound to
    `id = ANY(%s)`, which both psycopg drivers adapt to a Postgres array natively, rather
    than building one placeholder per id."""
    clauses=[]; params=[]
    if ids:
        clauses.append('id = ANY(%s)'); params.append(list(ids))
    if search:
        clauses.append('company ILIKE %s'); params.append(f'%{search}%')
    if risk in _V92_RISK_LEVELS:
        clauses.append('global_risk = %s'); params.append(risk)
    if period in _V92_PERIOD_SQL:
        clauses.append(_V92_PERIOD_SQL[period])
    where=('WHERE '+' AND '.join(clauses)) if clauses else ''
    return where,tuple(params)

def _v92_fetch_scan_history(search='',page=1,page_size=25,risk='',period='',ids=None):
    """Returns (rows, total_count). rows is [] and total_count is 0 if the feature
    isn't configured/available -- callers render an empty/unconfigured state rather
    than erroring."""
    global _V92_LAST_ERROR
    conn=_v92_db_connect()
    if conn is None:
        return [],0
    try:
        if not _v92_ensure_table(conn):
            return [],0
        where,params=_v92_build_filters(search,risk,period,ids)
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM scan_history {where}',params)
            total=cur.fetchone()[0]
            offset=max(0,(page-1)*page_size)
            cur.execute(
                f'''SELECT id,scanned_at,scan_type,company,sector,input_url,global_score,global_risk,
                           green_score,social_score,audience,findings_count,summary,
                           sector_risk,empco_blacklisted_count,high_risk_findings_count
                    FROM scan_history {where}
                    ORDER BY scanned_at DESC LIMIT %s OFFSET %s''',
                params+(page_size,offset))
            cols=['id','scanned_at','scan_type','company','sector','input_url','global_score','global_risk',
                  'green_score','social_score','audience','findings_count','summary',
                  'sector_risk','empco_blacklisted_count','high_risk_findings_count']
            rows=[dict(zip(cols,r)) for r in cur.fetchall()]
        return rows,total
    except Exception as e:
        _V92_LAST_ERROR=_v92_redact_error('fetch failed: '+str(e))
        return [],0
    finally:
        conn.close()

def _v92_fetch_stats(search='',risk='',period='',ids=None):
    """Aggregate counts/averages for the stats block at the top of /history, scoped to
    whatever filters are currently applied. Returns safe all-zero defaults if the
    feature isn't configured/available rather than erroring."""
    empty={'total':0,'avg_score':None,'this_month':0,'by_risk':{}}
    conn=_v92_db_connect()
    if conn is None:
        return empty
    try:
        if not _v92_ensure_table(conn):
            return empty
        where,params=_v92_build_filters(search,risk,period,ids)
        month_where=where+(' AND ' if where else 'WHERE ')+_V92_PERIOD_SQL['month']
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*), AVG(global_score) FROM scan_history {where}',params)
            total,avg_score=cur.fetchone()
            cur.execute(f'SELECT COUNT(*) FROM scan_history {month_where}',params)
            this_month=cur.fetchone()[0]
            cur.execute(f'SELECT global_risk, COUNT(*) FROM scan_history {where} GROUP BY global_risk',params)
            by_risk=dict(cur.fetchall())
        return {'total':total or 0,'avg_score':round(float(avg_score),1) if avg_score is not None else None,
                'this_month':this_month or 0,'by_risk':by_risk}
    except Exception:
        return empty
    finally:
        conn.close()

def _v92_fetch_all_for_export(search='',risk='',period='',ids=None):
    """Un-paginated fetch of every column, for CSV export -- scan volumes here are modest
    (tens to low hundreds a month), so a single full query is fine without its own
    pagination; callers stream the result straight into a CSV response."""
    conn=_v92_db_connect()
    if conn is None:
        return []
    try:
        if not _v92_ensure_table(conn):
            return []
        where,params=_v92_build_filters(search,risk,period,ids)
        with conn.cursor() as cur:
            cur.execute(f'''SELECT {",".join(_V92_EXPORT_COLUMNS)} FROM scan_history {where}
                             ORDER BY scanned_at DESC''',params)
            return [dict(zip(_V92_EXPORT_COLUMNS,r)) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _v92_parse_ids(source):
    """Shared id-list validation for both the GET ?ids=..&ids=.. query-string form (View
    selected -- a plain HTML GET form turns checked checkboxes into repeated query params
    natively, no JS needed) and the POST form-body form (Export selected). Silently drops
    anything that isn't a plain integer rather than trusting it -- these are meant to be
    checkbox values this same page rendered, but the request is still client-controlled.
    `source` is whatever a parse_qs() call already returned (a dict of str -> list[str])."""
    out=[]
    for v in source.get('ids',[]):
        try: out.append(int(v))
        except (TypeError,ValueError): pass
    return out

def _v92_rows_to_csv(rows):
    """CSV is not HTML -- no escaping concern here, values go straight into cells as-is
    (csv.writer handles quoting/delimiter-escaping itself). A UTF-8 BOM is prefixed so the
    file opens with correct encoding directly in Excel, not just in text editors/Sheets."""
    buf=io.StringIO()
    writer=csv.writer(buf)
    writer.writerow(_V92_EXPORT_COLUMNS)
    for r in rows:
        writer.writerow([str(r.get(c,'') if r.get(c) is not None else '') for c in _V92_EXPORT_COLUMNS])
    return b'\xef\xbb\xbf'+buf.getvalue().encode('utf-8')

def _v92_history_cookie_value():
    """HMAC-signed, timestamped token proving the shared history password was supplied
    correctly -- reuses the same signing-key infrastructure already used for report
    tokens, so no new secret material is introduced for this feature."""
    ts=str(int(time.time()))
    sig=hmac.new(_REPORT_SIGNING_KEY,('history-auth:'+ts).encode(),hashlib.sha256).hexdigest()
    return f'{ts}.{sig}'

def _v92_valid_history_cookie(cookie_header):
    if not HISTORY_ADMIN_PASSWORD:
        return False
    cookies=_v92_parse_cookies(cookie_header)
    value=cookies.get(_HISTORY_COOKIE_NAME,'')
    if not value or '.' not in value:
        return False
    ts_str,_,sig=value.partition('.')
    try:
        ts=int(ts_str)
    except ValueError:
        return False
    if time.time()-ts>_HISTORY_SESSION_SECONDS:
        return False
    expected=hmac.new(_REPORT_SIGNING_KEY,('history-auth:'+ts_str).encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,sig)

def _v92_parse_cookies(header):
    out={}
    for part in (header or '').split(';'):
        if '=' in part:
            k,_,v=part.strip().partition('=')
            if k: out[k]=v
    return out

_V92_STYLE='''
:root{--bg:#f6f8fb;--card:#ffffff;--ink:#132033;--muted:#5e6b7d;--line:#dfe5ee;--accent:#265f5c;--accent2:#173f5f;
--danger:#a43c3c;--danger-soft:#fff1f1;--warn:#9b6a17;--warn-soft:#fff8ea;--ok:#276749;--ok-soft:#edf7f0;--shadow:0 8px 24px rgba(20,35,55,.08);--radius:14px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Segoe UI,Roboto,Arial,sans-serif;font-size:15px}
.wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:26px;margin:0 0 4px}.muted{color:var(--muted)}.small{font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow);margin-top:18px}
input[type=text],input[type=password]{width:100%;border:1.5px solid var(--line);border-radius:10px;padding:11px;font:inherit}
select{border:1.5px solid var(--line);border-radius:10px;padding:10px;font:inherit;background:#fff}
.btn{border:0;border-radius:10px;background:var(--accent);color:#fff;padding:10px 16px;font-weight:700;cursor:pointer;font-size:14px;text-decoration:none;display:inline-block}
.btn.secondary{background:#eef3f8;color:#173f5f;border:1px solid #ccd8e4}
.error{margin-top:12px;padding:10px 12px;border-radius:10px;background:#fff0f0;border:1px solid #e2baba;color:#842424}
.notice{margin-bottom:14px;padding:10px 12px;border-radius:10px;background:#eef6f5;border:1px solid #cddfdd;color:#244744}
table{width:100%;border-collapse:collapse;margin-top:6px}th,td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#516073;background:#f7f9fc}td{font-size:13.5px}
.risk-badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:700}
.risk-badge.low{background:var(--ok-soft);color:var(--ok)}.risk-badge.medium{background:var(--warn-soft);color:var(--warn)}
.risk-badge.high,.risk-badge.very-high{background:var(--danger-soft);color:var(--danger)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin-bottom:6px}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.stat strong{display:block;font-size:24px;color:var(--accent2)}
.stat span{display:block;font-size:12px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.03em}
.pager{display:flex;gap:8px;margin-top:14px}
.empty{color:var(--muted);font-style:italic;padding:20px 0}
a{color:var(--accent2)}
@media(max-width:700px){.stats-row{grid-template-columns:1fr 1fr}}
'''

def _v92_risk_badge(risk):
    cls=str(risk or '').lower().replace(' ','-')
    return f'<span class="risk-badge {cls}">{risk or "—"}</span>'

def _v92_render_history_login(error=None):
    err_html=f'<div class="error">{error}</div>' if error else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Scan history &mdash; login</title>
<style>{_V92_STYLE}</style></head><body><div class="wrap" style="max-width:420px">
<h1>Scan history</h1><p class="muted">This page is private. Enter the shared password to continue.</p>
<div class="card"><form method="POST" action="/history/login">
<label class="small" for="pw">Password</label><br>
<input type="password" id="pw" name="password" autofocus>
{err_html}
<div style="margin-top:14px"><button class="btn" type="submit">Log in</button></div>
</form></div></div></body></html>'''

def _v92_option(value,label,current):
    sel=' selected' if value==current else ''
    return f'<option value="{value}"{sel}>{label}</option>'

def _v92_render_history_page(rows,total,page,page_size,search,risk='',period='',stats=None,ids=None):
    # Every value below either comes from the database (company/sector/input_url were
    # themselves derived from a user-supplied scan input, so are NOT trusted) or directly
    # from the request's own query string (the search box's echoed value) -- all of it is
    # HTML-escaped before interpolation to avoid a stored/reflected XSS via a scan input or
    # search query containing HTML. risk/period only ever come from a fixed, hardcoded
    # option list (_V92_RISK_LEVELS / _V92_PERIOD_SQL keys); ids are already validated as
    # plain integers by _v92_parse_ids() before reaching here -- none of the three need
    # escaping.
    ids=ids or []
    search_safe=html_escape(search)
    stats=stats or {'total':0,'avg_score':None,'this_month':0,'by_risk':{}}
    by_risk=stats.get('by_risk') or {}
    high_plus=(by_risk.get('High',0) or 0)+(by_risk.get('Very high',0) or 0)
    stats_html=f'''<div class="stats-row">
<div class="stat"><strong>{stats.get("total",0)}</strong><span>Scans (current filter)</span></div>
<div class="stat"><strong>{stats.get("this_month",0)}</strong><span>This month</span></div>
<div class="stat"><strong>{stats.get("avg_score") if stats.get("avg_score") is not None else "—"}</strong><span>Average global score</span></div>
<div class="stat"><strong>{high_plus}</strong><span>High / Very high risk</span></div>
</div>'''
    if not DATABASE_URL:
        body='<div class="empty">Scan history is not configured for this deployment (no DATABASE_URL set).</div>'
    elif not rows and not (search or risk or period or ids):
        body='<div class="empty">No scans logged yet.</div>'
    elif not rows:
        body='<div class="empty">No scans match the current search/filters.</div>'
    else:
        trs=[]
        for r in rows:
            when=html_escape(str(r.get('scanned_at') or '')[:16].replace('T',' '))
            company=html_escape(str(r.get('company') or '—'))
            # v92.4: company['sector'] is a real descriptive label only for the small
            # hardcoded PROFILES list (KBC, Delhaize...) -- otherwise it's the generic
            # placeholder "Sector not explicitly identified", which told the viewer
            # nothing. Fall back to the always-computed sector RISK level (Low/Medium/
            # High, from infer_sector()) when the name itself isn't a real label.
            sector_name=str(r.get('sector') or '')
            if sector_name and 'not explicitly identified' not in sector_name.lower():
                sector=html_escape(sector_name)
            elif r.get('sector_risk'):
                sector=f'Sector risk: {html_escape(str(r.get("sector_risk")))}'
            else:
                sector=''
            input_url=html_escape(str(r.get('input_url') or '')[:60])
            # v92.5: row id, needed so "Export selected" knows exactly which rows were
            # checked -- not part of any display value, so no escaping concern (it's an
            # integer straight from the database's own SERIAL primary key).
            row_id=r.get('id')
            trs.append(f'''<tr>
<td><input type="checkbox" class="row-check" name="ids" value="{row_id}" form="selectForm"></td>
<td>{when}</td>
<td><strong>{company}</strong><div class="small">{sector}</div></td>
<td class="small">{input_url}</td>
<td>{r.get("global_score") if r.get("global_score") is not None else "—"} {_v92_risk_badge(r.get("global_risk"))}</td>
<td>{r.get("green_score") if r.get("green_score") is not None else "—"}</td>
<td>{r.get("social_score") if r.get("social_score") is not None else "—"}</td>
<td>{r.get("findings_count") if r.get("findings_count") is not None else "—"}</td>
</tr>''')
        body=f'''<table><thead><tr><th><input type="checkbox" id="selectAll" title="Select all"></th><th>Date</th><th>Company</th><th>Input</th><th>Global</th><th>Green</th><th>Social</th><th>Findings</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table>'''
    total_pages=max(1,(total+page_size-1)//page_size)
    extra_q=(f'&q={quote(search)}' if search else '')+(f'&risk={quote(risk)}' if risk else '')+(f'&period={quote(period)}' if period else '')
    # v92.6: an active ids selection-filter (from "View selected") is preserved across
    # pagination and the plain "Export CSV" link the same way search/risk/period already
    # are -- each id is its own repeated ?ids=N query param, matching exactly what the
    # GET form itself produces when submitted, so a bookmarked/shared URL round-trips.
    ids_q=''.join(f'&ids={i}' for i in ids)
    full_q=extra_q+ids_q
    pager=''
    if total_pages>1:
        prev=f'<a class="btn secondary" href="/history?page={page-1}{full_q}">&larr; Previous</a>' if page>1 else ''
        nxt=f'<a class="btn secondary" href="/history?page={page+1}{full_q}">Next &rarr;</a>' if page<total_pages else ''
        pager=f'<div class="pager">{prev}<span class="small" style="align-self:center">Page {page} of {total_pages} &middot; {total} scan(s)</span>{nxt}</div>'
    risk_options=''.join(_v92_option(v,v,risk) for v in _V92_RISK_LEVELS)
    period_options=''.join(_v92_option(k,l,period) for k,l in (('month','This month'),('30d','Last 30 days'),('90d','Last 90 days')))
    has_filters=bool(search or risk or period or ids)
    clear_selection_href='/history?'+extra_q.lstrip('&') if extra_q else '/history'
    selection_banner=(f'<div class="notice">Showing {len(ids)} selected scan(s). '
                       f'<a href="{clear_selection_href}">Clear selection</a></div>') if ids else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Scan history</title>
<style>{_V92_STYLE}</style></head><body><div class="wrap">
<div class="toolbar"><div><h1>Scan history</h1><p class="small">Every completed scan on this deployment.</p></div>
<a class="btn secondary" href="/history/logout">Log out</a></div>
{stats_html}
<div class="card">
<form method="GET" action="/history" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center">
<input type="text" name="q" placeholder="Search by company name" style="flex:1;min-width:180px" value="{search_safe}">
<select name="risk"><option value="">All risk levels</option>{risk_options}</select>
<select name="period"><option value="">All time</option>{period_options}</select>
<button class="btn" type="submit">Filter</button>
{'<a class="btn secondary" href="/history">Clear</a>' if has_filters else ''}
<a class="btn secondary" href="/history/export.csv?q={quote(search)}&risk={quote(risk)}&period={quote(period)}{ids_q}">Export CSV</a>
</form>
{selection_banner}
<form id="selectForm" method="POST" action="/history/export_selected"></form>
{body}
<div style="margin-top:12px;display:flex;gap:8px">
<button class="btn secondary" type="submit" form="selectForm" formaction="/history" formmethod="GET" id="viewSelectedBtn" disabled>View selected</button>
<button class="btn secondary" type="submit" form="selectForm" id="exportSelectedBtn" disabled>Export selected</button>
</div>
{pager}
</div></div>
<script>
(function(){{
  var all=document.getElementById('selectAll'), boxes=document.querySelectorAll('.row-check'),
      exportBtn=document.getElementById('exportSelectedBtn'), viewBtn=document.getElementById('viewSelectedBtn');
  function sync(){{ var any=false; boxes.forEach(function(b){{ if(b.checked) any=true; }}); if(exportBtn) exportBtn.disabled=!any; if(viewBtn) viewBtn.disabled=!any; }}
  if(all) all.addEventListener('change',function(){{ boxes.forEach(function(b){{ b.checked=all.checked; }}); sync(); }});
  boxes.forEach(function(b){{ b.addEventListener('change',sync); }});
}})();
</script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version=f'DurablyScan/{APP_RELEASE_LABEL}'

    def _allowed_origin(self):
        origin=(self.headers.get('Origin') or '').rstrip('/')
        if not origin: return ''
        try: same_host=(urlparse(origin).netloc.lower()==(self.headers.get('Host') or '').lower())
        except Exception: same_host=False
        return origin if same_host or origin in ALLOWED_ORIGINS else ''

    def _send(self,body,ctype="text/html; charset=utf-8",status=200,extra_headers=None):
        if isinstance(body,str): body=body.encode()
        self.send_response(status); self.send_header('Content-Type',ctype)
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','same-origin')
        allowed=self._allowed_origin()
        if allowed:
            self.send_header('Access-Control-Allow-Origin',allowed); self.send_header('Vary','Origin')
            self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.send_header('Access-Control-Allow-Headers','Content-Type')
        for k,v in (extra_headers or {}).items(): self.send_header(k,v)
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

    def _json(self,d,status=200): self._send(json.dumps(d,ensure_ascii=False,indent=2),'application/json; charset=utf-8',status)

    def _read_json(self):
        try: n=int(self.headers.get('Content-Length',0) or 0)
        except Exception: n=0
        if n<=0: return {}
        if n>MAX_REQUEST_BYTES: raise OverflowError(f'Request exceeds the {MAX_REQUEST_BYTES//1_000_000} MB application limit.')
        try: return json.loads(self.rfile.read(n).decode('utf-8') or '{}')
        except Exception as exc: raise ValueError('Request body is not valid JSON.') from exc

    def _resolve_report_payload(self,data):
        """Returns (payload, error_response); error_response is None on success."""
        if not data: return None,self._json({'error':'No report token or scan result provided'},400)
        token=data.get('report_token') or data.get('_report_token')
        if token:
            try: return decode_report_token(token),None
            except ValueError as exc: return None,self._json({'error':str(exc)},403)
        # Backward-compatible path for a v68 result that has not passed through JavaScript
        # numeric normalisation. New v69 scans use report_token.
        if verify_report_signature(data): return data,None
        return None,self._json({'error':'The report download token is missing or invalid. Run a new scan before downloading the report.'},403)

    def _respond_pdf(self,scan_result):
        build_fn=_get_build_company_report_pdf()
        if build_fn is None: return self._json({'error':'PDF report generation is unavailable: '+(_report_pdf_import_error or 'unknown import error')},500)
        try: pdf_bytes=build_fn(_unsigned_report_payload(scan_result))
        except Exception as e: return self._json({'error':'Could not generate PDF report: '+str(e)},500)
        stamp=re.sub(r'[^0-9-]','',(scan_result.get('analysis_date') or datetime.date.today().isoformat())[:10])
        fname=f'durably_company_report_{stamp or datetime.date.today().isoformat()}.pdf'
        return self._send(pdf_bytes,'application/pdf',200,{'Content-Disposition':f'attachment; filename="{fname}"'})

    def do_HEAD(self):
        # v73: mirror do_GET's actual route set instead of unconditionally returning 200,
        # so monitoring/uptime checks against a nonexistent path get a real 404.
        if self.path=='/' or self.path.startswith('/?'):
            return self._send(b'',status=200)
        if self.path=='/methodology.pdf':
            return self._send(b'',status=200 if (APP_DIR/'methodology.pdf').exists() else 404)
        if self.path=='/api/health':
            return self._send(b'',status=200)
        return self._send(b'',status=404)
    def do_OPTIONS(self):
        if self.headers.get('Origin') and not self._allowed_origin(): return self._json({'error':'Origin is not allowed.'},403)
        return self._json({'ok':True})

    def do_GET(self):
        if self.path=='/' or self.path.startswith('/?'):
            html=(APP_DIR/'frontend.html').read_text(encoding='utf-8')
            html=html.replace('{{APP_VERSION}}',APP_VERSION).replace('{{APP_RELEASE_LABEL}}',APP_RELEASE_LABEL).replace('{{APP_RELEASE_DATE}}',APP_RELEASE_DATE)
            return self._send(html)
        if self.path=='/methodology.pdf':
            pdf=APP_DIR/'methodology.pdf'; return self._send(pdf.read_bytes(),'application/pdf') if pdf.exists() else self._json({'error':'Methodology PDF not found'},404)
        if self.path=='/api/health':
            # v73: report_pdf_available previously defaulted to True before the lazy PDF import
            # had ever actually been attempted (report_pdf_fn and report_pdf_import_error both
            # start as None). Force the import here so the flag reflects a real, current test
            # rather than an optimistic assumption. Each component below is now checked
            # independently, so "status: ok" cannot mask a broken PDF/methodology/report-signing
            # component.
            report_pdf_ok=_get_build_company_report_pdf() is not None
            methodology_pdf_ok=(APP_DIR/'methodology.pdf').exists()
            components={
                'scan_engine':True,
                'report_pdf':report_pdf_ok,
                'methodology_pdf':methodology_pdf_ok,
                'external_search':external_search_configured(),
                'email_service':bool(BREVO_API_KEY and BREVO_SENDER_EMAIL),
                'report_signing_key':_REPORT_SIGNING_KEY_CONFIGURED,
            }
            # Only components that should always work regardless of deployment/config choices
            # (scan engine, PDF generation) gate the overall status; external_search, email and
            # the report-signing key are optional/deployment-specific and are surfaced as their
            # own fields rather than flipping the whole service to "degraded".
            core_ok=all(components[k] for k in ('scan_engine','report_pdf','methodology_pdf'))
            return self._json({'status':'ok' if core_ok else 'degraded','version':APP_VERSION,'release':APP_RELEASE_LABEL,'release_date':APP_RELEASE_DATE,
                               'components':components,
                               'tavily_configured':bool(TAVILY_API_KEY),'serper_configured':bool(SERPER_API_KEY),'google_search_configured':bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX),
                               'google_api_key_configured':bool(GOOGLE_SEARCH_API_KEY),'google_cx_configured':bool(GOOGLE_SEARCH_CX),
                               'external_search_configured':components['external_search'],
                               'report_pdf_available':report_pdf_ok,'methodology_pdf_available':methodology_pdf_ok,
                               'report_token_enabled':True,'report_signing_key_configured':_REPORT_SIGNING_KEY_CONFIGURED,
                               'email_delivery_configured':bool(BREVO_API_KEY and BREVO_SENDER_EMAIL),'email_sender_set':bool(BREVO_SENDER_EMAIL),
                               # v91.3: surfaces the EFFECTIVE crawl-coverage config this running
                               # process actually resolved (env var if set and within its clamp,
                               # otherwise the default) -- added after a render.yaml env-var bump
                               # left it unclear, without a dashboard login, whether Render's
                               # blueprint sync had actually picked up the new values on deploy.
                               'crawl_config':{'CRAWL_TARGET_EXTRA_PAGES':CRAWL_TARGET_EXTRA_PAGES,'CRAWL_MAX_PAGE_ATTEMPTS':CRAWL_MAX_PAGE_ATTEMPTS,
                                   'CRAWL_BUDGET_SECONDS':CRAWL_BUDGET_SECONDS,'CRAWL_FETCH_WORKERS':CRAWL_FETCH_WORKERS,
                                   'EXTERNAL_SIGNAL_MAX_QUERIES':EXTERNAL_SIGNAL_MAX_QUERIES,'EXTERNAL_SIGNAL_RESULTS_PER_QUERY':EXTERNAL_SIGNAL_RESULTS_PER_QUERY,
                                   'EXTERNAL_SIGNAL_WORKERS':EXTERNAL_SIGNAL_WORKERS},
                               'container_cpu':_v91_4_container_cpu_quota(),
                               # v92.1: history_configured mirrors the other optional-feature
                               # flags above; history_last_error surfaces the most recent
                               # scan-history save/connect failure (if any) since this process
                               # started, without needing dashboard/log access to diagnose why
                               # a scan silently didn't appear on /history.
                               'history_configured':bool(DATABASE_URL and HISTORY_ADMIN_PASSWORD),
                               'history_last_error':_V92_LAST_ERROR})
        if self.path=='/history' or self.path.startswith('/history?'):
            if not (DATABASE_URL and HISTORY_ADMIN_PASSWORD):
                return self._send(_v92_render_history_page([],0,1,25,''))
            if not _v92_valid_history_cookie(self.headers.get('Cookie')):
                return self._send(_v92_render_history_login())
            qs=parse_qs(urlparse(self.path).query)
            search=(qs.get('q',[''])[0] or '').strip()[:200]
            risk=(qs.get('risk',[''])[0] or '').strip()
            period=(qs.get('period',[''])[0] or '').strip()
            ids=_v92_parse_ids(qs)
            try: page=max(1,int(qs.get('page',['1'])[0]))
            except Exception: page=1
            page_size=25
            rows,total=_v92_fetch_scan_history(search,page,page_size,risk,period,ids)
            stats=_v92_fetch_stats(search,risk,period,ids)
            return self._send(_v92_render_history_page(rows,total,page,page_size,search,risk,period,stats,ids))
        if self.path=='/history/export.csv' or self.path.startswith('/history/export.csv?'):
            if not (DATABASE_URL and HISTORY_ADMIN_PASSWORD):
                return self._json({'error':'Scan history is not configured for this deployment.'},404)
            if not _v92_valid_history_cookie(self.headers.get('Cookie')):
                return self._json({'error':'Not logged in. Open /history in a browser first.'},401)
            qs=parse_qs(urlparse(self.path).query)
            search=(qs.get('q',[''])[0] or '').strip()[:200]
            risk=(qs.get('risk',[''])[0] or '').strip()
            period=(qs.get('period',[''])[0] or '').strip()
            ids=_v92_parse_ids(qs)
            rows=_v92_fetch_all_for_export(search,risk,period,ids)
            csv_bytes=_v92_rows_to_csv(rows)
            stamp=datetime.date.today().isoformat()
            return self._send(csv_bytes,'text/csv; charset=utf-8',200,
                {'Content-Disposition':f'attachment; filename="scan_history_{stamp}.csv"'})
        if self.path=='/history/logout':
            return self._send(_v92_render_history_login(),status=200,
                extra_headers={'Set-Cookie':f'{_HISTORY_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax'})
        return self._json({'error':'Not found'},404)

    def _handle_history_login(self):
        """POST /history/login submits a plain HTML form (application/x-www-form-urlencoded,
        not JSON), so it is handled entirely separately from do_POST's JSON-only body
        parsing below -- routed here before that generic path is ever reached."""
        try: n=int(self.headers.get('Content-Length',0) or 0)
        except Exception: n=0
        raw=self.rfile.read(n) if n>0 else b''
        form=parse_qs(raw.decode('utf-8','ignore'))
        submitted=(form.get('password',[''])[0] or '')
        if HISTORY_ADMIN_PASSWORD and hmac.compare_digest(submitted,HISTORY_ADMIN_PASSWORD):
            cookie_val=_v92_history_cookie_value()
            return self._send(b'',status=302,extra_headers={
                'Location':'/history',
                'Set-Cookie':f'{_HISTORY_COOKIE_NAME}={cookie_val}; Max-Age={_HISTORY_SESSION_SECONDS}; Path=/; HttpOnly; SameSite=Lax'})
        return self._send(_v92_render_history_login('Incorrect password.'),status=401)

    def _handle_history_export_selected(self):
        """POST /history/export_selected submits a plain HTML form (the row checkboxes on
        /history, application/x-www-form-urlencoded, not JSON) -- handled separately from
        do_POST's JSON-only body parsing below, same as the login form above."""
        if not (DATABASE_URL and HISTORY_ADMIN_PASSWORD):
            return self._json({'error':'Scan history is not configured for this deployment.'},404)
        if not _v92_valid_history_cookie(self.headers.get('Cookie')):
            return self._json({'error':'Not logged in. Open /history in a browser first.'},401)
        try: n=int(self.headers.get('Content-Length',0) or 0)
        except Exception: n=0
        raw=self.rfile.read(n) if n>0 else b''
        form=parse_qs(raw.decode('utf-8','ignore'))
        ids=_v92_parse_ids(form)
        rows=_v92_fetch_all_for_export(ids=ids) if ids else []
        csv_bytes=_v92_rows_to_csv(rows)
        stamp=datetime.date.today().isoformat()
        return self._send(csv_bytes,'text/csv; charset=utf-8',200,
            {'Content-Disposition':f'attachment; filename="scan_history_selected_{stamp}.csv"'})

    def do_POST(self):
        client=_client_ip(self)
        if self.path=='/history/login':
            return self._handle_history_login()
        if self.path=='/history/export_selected':
            return self._handle_history_export_selected()
        try:
            data=self._read_json()
            if self.path in {'/api/scan/url','/api/scan/document'}:
                if not _rate_limit_allowed(client,'scan',RATE_LIMIT_SCANS): return self._json({'error':'Scan rate limit reached. Try again later.'},429)
                if not _SCAN_SEMAPHORE.acquire(blocking=False): return self._json({'error':'The scan service is busy. Try again in a few moments.'},429)
                try:
                    if self.path=='/api/scan/url':
                        u=data.get('url','')
                        if not u: return self._json({'error':'No URL provided'},400)
                        result=analyse_url(u)
                        _v92_save_scan_history(result,'url',client)
                    else:
                        filename=data.get('filename','uploaded_document'); content=data.get('content_base64','')
                        if not content: return self._json({'error':'No document content provided'},400)
                        txt=decode_uploaded_document(filename,content,data.get('mime_type',''))
                        result=analyse_uploaded_document(filename,txt,data.get('company_name',''))
                        _v92_save_scan_history(result,'document',client)
                    if data.get('format')=='pdf': return self._respond_pdf(result)
                    return self._json(attach_report_signature(result))
                finally: _SCAN_SEMAPHORE.release()
            if self.path=='/api/report/pdf':
                if not _rate_limit_allowed(client,'report',RATE_LIMIT_REPORTS): return self._json({'error':'Report download rate limit reached. Try again later.'},429)
                payload,err=self._resolve_report_payload(data)
                if err is not None: return err
                return self._respond_pdf(payload)
            if self.path=='/api/report/email':
                if not _rate_limit_allowed(client,'report',RATE_LIMIT_REPORTS): return self._json({'error':'Report email rate limit reached. Try again later.'},429)
                email=(data.get('email') or '').strip()
                if not is_valid_email(email): return self._json({'error':'Please enter a valid email address.'},400)
                payload,err=self._resolve_report_payload(data)
                if err is not None: return err
                build_fn=_get_build_company_report_pdf()
                if build_fn is None: return self._json({'error':'PDF report generation is unavailable: '+(_report_pdf_import_error or 'unknown import error')},500)
                try: pdf_bytes=build_fn(_unsigned_report_payload(payload))
                except Exception as e: return self._json({'error':'Could not generate PDF report: '+str(e)},500)
                stamp=re.sub(r'[^0-9-]','',(payload.get('analysis_date') or datetime.date.today().isoformat())[:10]) or datetime.date.today().isoformat()
                comp=payload.get('company'); company_name=comp.get('company','') if isinstance(comp,dict) else ''
                try: send_report_pdf_email(email,pdf_bytes,company_name,stamp)
                except RuntimeError as exc: return self._json({'error':str(exc)},500)
                return self._json({'ok':True,'message':f'Report sent to {email}.'})
            return self._json({'error':'Unknown endpoint'},404)
        except OverflowError as e: return self._json({'error':str(e)},413)
        except ValueError as e: return self._json({'error':str(e)},400)
        except Exception as e: return self._json({'error':str(e)},500)

# V55 claim-signal sensitivity and report layout refinements

# The scan should retain enough claim signals to be useful, but only where wording is a real
# sustainability claim signal (not a neutral reference such as 'backing British suppliers').
V55_GREEN_EXTRA_PATTERNS = [
    ('Generic environmental claim', 'High', [
     # Cross-sector generic wording, plus fashion/textile examples (the pattern this list was
     # originally built from) -- kept alongside, not replaced by, equivalents for food/beverage,
     # cosmetics, construction, electronics, automotive/mobility, energy and general business
     # wording, so the scan is not structurally biased toward apparel retailers.
     'more sustainable','sustainable product','sustainable products','sustainable collection','sustainable range','sustainable choice','sustainable materials','sustainably sourced','responsibly sourced material','responsible materials','lower-impact material','low-impact material','eco-design','eco design','preferred materials',
     'sustainable fashion','sustainable clothing','sustainable garment','sustainable garments','sustainable cotton','sustainable viscose','sustainable fibres','sustainable fibers','conscious collection','join life',
     'sustainable ingredients','sustainably sourced ingredients','sustainable farming','sustainable agriculture','sustainable food','sustainable packaging','sustainably farmed','sustainably grown',
     'sustainable formula','sustainable beauty',
     'sustainable building','sustainable construction','sustainable building materials',
     'sustainable electronics','sustainable technology',
     'sustainable mobility','sustainable transport','sustainable transportation','sustainable vehicle','sustainable vehicles',
     'sustainable energy','sustainable banking','sustainable investment','sustainable finance',
     'duurzamer','duurzaam product','duurzame producten','duurzame collectie','duurzaam gamma','duurzame keuze','duurzame materialen','duurzaam ingekocht','verantwoord ingekocht materiaal','verantwoorde materialen','materiaal met lagere impact','voorkeursmaterialen',
     'duurzame mode','duurzame kleding','duurzaam kledingstuk','duurzame kledingstukken','duurzaam katoen','duurzame viscose','duurzame vezels','bewuste collectie',
     'duurzame ingrediënten','duurzaam ingekochte ingrediënten','duurzame landbouw','duurzaam voedsel','duurzame verpakking','duurzaam geteeld',
     'duurzame formule','duurzame schoonheidsproducten',
     'duurzaam bouwen','duurzame bouwmaterialen',
     'duurzame elektronica','duurzame technologie',
     'duurzame mobiliteit','duurzaam transport','duurzaam voertuig','duurzame voertuigen',
     'duurzame energie','duurzaam bankieren','duurzaam beleggen','duurzame financiering',
     'plus durable','plus durables','produit durable','produits durables','collection durable','gamme durable','choix durable','matériaux durables','sourcé de manière durable','matériau responsable','matériaux responsables','matériau à impact réduit','éco-conception','matériaux préférés',
     'mode durable','vêtements durables','vêtement durable','coton durable','viscose durable','fibres durables','collection consciente',
     'ingrédients durables','ingrédients d\'origine durable','agriculture durable','alimentation durable','emballage durable','cultivé de manière durable',
     'formule durable','beauté durable',
     'construction durable','matériaux de construction durables',
     'électronique durable','technologie durable',
     'mobilité durable','transport durable','véhicule durable','véhicules durables',
     'énergie durable','banque durable','investissement durable','finance durable'],
     'EmpCo risk: broad environmental wording such as sustainable, eco, conscious, preferred or lower-impact can be misleading where the exact environmental attribute, scope and evidence are not clear on the same medium.',
     'Specify the exact attribute, product/material scope, baseline, method, evidence, reporting period and limitations.'),
    ('Recycled / recyclable material claim', 'Medium', ['recycled polyester','recycled cotton','recycled plastic','recycled aluminium','recycled aluminum','recycled steel','recycled glass','recycled paper','recycled cardboard','recycled metal','recycled electronics','recycled material','recycled materials','made from recycled','made with recycled','recyclable packaging','recycled packaging','recyclable materials','circular material','circular materials','is recyclable','are recyclable','fully recyclable','widely recyclable','easily recyclable','recyclable bottle','recyclable container',
     'gerecycleerd polyester','gerecycleerd katoen','gerecycleerd plastic','gerecycleerd aluminium','gerecycleerd staal','gerecycleerd glas','gerecycleerd papier','gerecycleerd karton','gerecycleerd metaal','gerecycleerde elektronica','gerecycleerd materiaal','gerecycleerde materialen','gemaakt van gerecycleerd','gemaakt met gerecycleerd','recycleerbare verpakking','gerecycleerde verpakking','recycleerbare materialen','circulair materiaal','circulaire materialen','is recycleerbaar','zijn recycleerbaar','volledig recycleerbaar','breed recycleerbaar','gemakkelijk recycleerbaar','recycleerbare fles',
     'polyester recyclé','coton recyclé','plastique recyclé','aluminium recyclé','acier recyclé','verre recyclé','papier recyclé','carton recyclé','métal recyclé','électronique recyclée','matériau recyclé','matériaux recyclés','fabriqué à partir de matériaux recyclés','fabriqué avec des matériaux recyclés','emballage recyclable','emballage recyclé','matériaux recyclables','matériau circulaire','matériaux circulaires','est recyclable','sont recyclables','entièrement recyclable','largement recyclable','facilement recyclable','bouteille recyclable','contenant recyclable'],
     'Recycled, recyclable or circular-material wording can be a sustainability claim where conditions, percentage, certification, local recyclability or material scope are unclear.',
     'State the recycled content percentage, material scope, certification or chain-of-custody basis, and practical recyclability conditions.'),
    ('Generic environmental claim', 'High', ['environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','eco-friendly','climate friendly','green choice','eco choice','green product','eco product',
     'milieuvriendelijk','milieuvriendelijke','beter voor de planeet','goed voor de planeet','klimaatvriendelijk','groene keuze','groen product',
     "respectueux de l'environnement",'respectueux du climat','meilleur pour la planète','bon pour la planète','choix vert','choix écologique','produit vert','produit écologique'],
     'EmpCo risk: generic environmental claims are high-sensitivity claims and may be prohibited if they are not specified clearly and prominently or backed by recognised excellent environmental performance.',
     'Replace generic wording with a specific, evidence-backed statement on the exact attribute and scope.'),
]

V55_SOCIAL_EXTRA_PATTERNS = [
    ('Supplier-responsibility / sourcing claim', 'High', ['responsible sourcing','responsibly sourced','ethical sourcing','ethically sourced','supplier code','supplier code of conduct','supplier standards','audited suppliers','certified suppliers','traceable suppliers','traceable supply chain','supply chain traceability','responsible supply chain','sustainable sourcing','all suppliers comply','all suppliers meet','supplier due diligence',
     'verantwoorde inkoop','verantwoord ingekocht','ethische inkoop','ethisch ingekocht','leverancierscode','gedragscode voor leveranciers','leveranciersnormen','geauditeerde leveranciers','gecertificeerde leveranciers','traceerbare leveranciers','traceerbare toeleveringsketen','traceerbaarheid van de toeleveringsketen','verantwoorde toeleveringsketen','duurzame inkoop','alle leveranciers voldoen','zorgvuldigheidsplicht leveranciers',
     'approvisionnement responsable','sourcing responsable','approvisionnement éthique','sourcé de manière éthique','code fournisseur','code de conduite des fournisseurs','normes fournisseurs','fournisseurs audités','fournisseurs certifiés','fournisseurs traçables','chaîne d\'approvisionnement traçable','traçabilité de la chaîne d\'approvisionnement','chaîne d\'approvisionnement responsable','sourcing durable','tous les fournisseurs sont conformes','devoir de vigilance fournisseurs'],
     'Supplier and sourcing claims can imply control over supply-chain conduct, audit quality, traceability, due diligence or compliance. They require scope, coverage, methodology, limitations and remediation evidence.',
     'State supplier tiers covered, audit/assessment method, traceability limits, worker voice, corrective-action closure and remediation approach.'),
    ('Human-rights / labour-rights claim', 'High', ['human rights due diligence','respect human rights','protect human rights','labour rights','labor rights','worker rights','fair wages','living wage','decent work','no child labour','no child labor',
     'zorgvuldigheidsplicht mensenrechten','respecteren mensenrechten','beschermen mensenrechten','arbeidsrechten','rechten van werknemers','eerlijke lonen','leefbaar loon','waardig werk','geen kinderarbeid',
     'devoir de vigilance droits humains','respect des droits humains','protection des droits humains','droits du travail','droits des travailleurs','salaires équitables','salaire vital','travail décent','aucun travail des enfants'],
     'Human-rights or labour-rights wording is a high-sensitivity social claim where due diligence, salient risks, grievance channels and remedy are not visible.',
     'Connect the claim to salient-risk assessment, governance, grievance channels, tracking and remedy.'),
    ('Forced-labour product or supply-chain claim', 'High', ['forced labour free','forced labor free','free from forced labour','free from forced labor','modern slavery free','no forced labour','no forced labor','forced-labour due diligence','forced labor due diligence',
     'vrij van dwangarbeid','geen dwangarbeid','vrij van moderne slavernij','zorgvuldigheidsplicht dwangarbeid',
     'sans travail forcé','exempt de travail forcé','aucun travail forcé','sans esclavage moderne','devoir de vigilance travail forcé'],
     'Forced-labour or modern-slavery assurance wording can create a product/supply-chain compliance impression under the EU Forced Labour Regulation lens.',
     'Scope the claim and document product/supplier traceability, forced-labour risk assessment, mitigation, remediation and withdrawal/customs response readiness.'),
    ('Broad social-impact claim', 'Medium', ['positive social impact','positive impact on communities','support communities','supporting communities','empowering communities','inclusive growth',
     'positieve sociale impact','positieve impact op gemeenschappen','ondersteunen van gemeenschappen','gemeenschappen versterken','inclusieve groei',
     'impact social positif','impact positif sur les communautés','soutien aux communautés','autonomisation des communautés','croissance inclusive'],
     'Broad community or social-impact wording can overstate outcomes where stakeholders, geography, metrics and limitations are not defined.',
     'Specify stakeholder group, geography, objective, indicators, period, evidence and limitations.'),
]

V55_NAV_CONTEXT_EXCLUSIONS = [
    'cookie', 'privacy', 'terms', 'login', 'sign in', 'menu', 'navigation', 'subscribe', 'newsletter',
    'download report', 'annual report', 'sustainability report', 'press release archive',
    'read more about', 'learn more about', 'find out more about', 'more about our',
    'explore our', 'discover our', 'read on to', 'click here', 'see more'
]

def _normalize_apostrophes(s):
    """Real web/PDF text almost always uses the typographic apostrophe (U+2019, e.g. from CMS
    output or a curly-quote font), but every French trigger and guard phrase in this file
    ("l'environnement", "l'acheteur est responsable", ...) is written with a plain straight
    apostrophe -- without this, those phrases silently never match curly-quote text, in either
    direction (missed triggers, and false-positive guards that fail to recognise text they were
    built to exclude)."""
    return (s or '').replace('’', "'").replace('‘', "'").replace('ʼ', "'")


_TRIGGER_RE_CACHE = {}
def _trigger_present(trigger, low_text):
    """Whole-word/phrase match instead of naive substring containment. Prevents
    short triggers from matching inside unrelated words, e.g. 'eco' inside
    'economic'/'ecosystem', or 'green' inside 'greenhouse gas emissions'."""
    rx = _TRIGGER_RE_CACHE.get(trigger)
    if rx is None:
        rx = re.compile(r'(?<![a-z0-9])' + re.escape(trigger) + r'(?![a-z0-9])')
        _TRIGGER_RE_CACHE[trigger] = rx
    return rx.search(low_text) is not None


DOC_TITLE_ENDINGS = ['code of conduct','code of ethics','policy','statement','charter',
                     'standards','standard','guidelines','framework','handbook']
ASSERTION_SIGNALS = ['compl','ensure','guarantee','audit','requir','monitor','verify','enforce',
                     'implement','adopt','commit','all suppliers','our suppliers are','we ensure',
                     'is designed to','are required','must ','has been','have been','in place to',
                     'demonstrat','proves','proven']

def _strip_title_decoration(s):
    """Strip trailing (PDF, 2MB)-style annotations, trailing years, and trailing dashes/colons/bullets
    so 'Supplier Code of Conduct (PDF, 2 MB)' or 'Supplier Code of Conduct 2024' still reduce to the
    bare title before the ending-match check runs."""
    prev=None
    while prev != s:
        prev=s
        s=re.sub(r'\s*[\(\[][^)\]]*[\)\]]\s*$','',s).strip()
        s=re.sub(r'\s*\b(19|20)\d{2}\b\s*$','',s).strip()
        s=re.sub(r'\s*[-\u2013\u2014:]\s*$','',s).strip()
        s=re.sub(r'^\s*[-\u2013\u2014\u2022*]\s*','',s).strip()
    return s

def _looks_like_bare_document_title(c):
    """True when an excerpt is just the NAME of a policy/programme document (e.g.
    'Supplier Code of Conduct.', 'Human Rights Policy', 'Supplier Code of Conduct (PDF, 2 MB)'),
    OR a concatenated list of several such titles (common in nav/footer link menus, e.g.
    'Human Rights Policy Supplier Code of Conduct Anti-Corruption Policy Modern Slavery Statement'),
    with no surrounding assertion. Naming a document a company has is not itself a claim -- only
    asserting compliance, outcomes or specifics against it is. Deliberately generic (covers any
    '<Something> Code of Conduct/Policy/Statement/...' title, singly or in a list), not specific to
    one phrase, since this pattern recurs across many companies' sites."""
    if any(sig in c for sig in ASSERTION_SIGNALS):
        return False
    stripped=_strip_title_decoration(c.strip().rstrip('.').strip())
    words=stripped.split()
    if not words:
        return False
    if len(words) <= 8 and any(stripped.endswith(end) for end in DOC_TITLE_ENDINGS):
        return True
    ending_hits=sum(1 for end in DOC_TITLE_ENDINGS if end in stripped)
    if ending_hits >= 2 and len(words) <= 20:
        return True
    return False

def _looks_like_toc_or_index(excerpt):
    """v57n: detect table-of-contents / section-index style text -- short heading fragments
    strung together (e.g. "MILIEU 1 Klimaatverandering * Klimaatadaptatie ... 2 Waterbeheer *
    Waterverbruik ... 3 Verantwoorde inkoop ...") rather than real prose. This is common in
    PDF-extracted report front-matter/navigation and, once digits or newlines get converted to
    periods during text normalisation, reads enough like a sentence to slip past the other
    checks -- even though no actual claim is being made, only chapter/section titles are being
    listed. Words like "verantwoorde inkoop" or "ethisch" appearing as a section heading in an
    index is not the same as the company asserting them as a claim."""
    c=(excerpt or '').strip()
    if not c:
        return False
    # Bullet-separated fragments (any bullet-like character used as a list separator).
    if sum(c.count(b) for b in ('\u2022','*','·')) >= 2:
        return True
    # A run of short fragments separated by isolated one/two-digit numbers immediately before a
    # capitalised word ("... 1 Klimaatverandering ... 2 Waterbeheer ...") is characteristic of a
    # numbered chapter/section list, not a sentence using numbers as data.
    digit_markers=len(re.findall(r'(?:^|\s)\d{1,2}(?=\s[A-Z])', c))
    if digit_markers >= 3:
        return True
    # High density of capitalised word-starts with no first/third-person sentence verbs at all is
    # typical of a list of headings ("Better planet Better life Better health...") rather than a
    # written claim.
    words=c.split()
    if len(words) >= 8:
        cap_starts=sum(1 for w in words if w[:1].isupper())
        if cap_starts/len(words) > 0.5 and not re.search(r'\b(we|our|is|are|has|have|will|to|wij|we|onze|zijn|heeft|hebben|zal|naar|nous|notre|nos|est|sont|a|ont|sera|à)\b', c.lower()):
            return True
    # v57n: very short excerpts made up of two or more bare, verb-less fragments (e.g.
    # "Responsible sourcing . Environment.") are typically adjacent section headings glued
    # together by newline-to-period normalisation, not a sentence -- catch this even below the
    # 8-word threshold above, which needs more words to safely judge capitalisation density.
    if len(c) < 70:
        frags=[f.strip() for f in re.split(r'[.!?]', c) if f.strip()]
        if len(frags) >= 2 and all(len(f.split()) <= 4 for f in frags):
            return True
    return False

def _looks_like_impersonal_non_claim(excerpt):
    """v76: two real-world false positives (found via live company scan alerts) share a root
    cause -- the excerpt describes something in general or third-party terms rather than the
    reviewed company asserting it about itself, and reads as ordinary prose so nothing else
    catches it. (1) An ESG-glossary page: "Carbon Neutral. Achieving a net-zero carbon footprint
    by balancing carbon emissions with carbon removal or offsetting." was flagged as if it were
    the company's own claim -- it is a definition of the term, not an assertion the company
    makes about itself. (2) A sourcing-policy clause: "the customer is responsible to conduct
    due diligence on its suppliers and ensure that only responsibly sourced material..." was
    flagged the same way -- the customer, not the reviewed company, is the actor. Both share one
    signal: no first-person company voice (we/our/us) anywhere in the excerpt, combined with
    either (a) a short capitalised term immediately followed by an impersonal, gerund-led
    definition sentence, or (b) a named third party (the customer/buyer/supplier/"you") as the
    one responsible for the described action. Badge/label-style short claims ("100% Recycled",
    "Carbon Neutral" on its own, with no definition sentence attached) match neither pattern and
    are unaffected."""
    c=_normalize_apostrophes(excerpt or '').strip()
    if not c or re.search(r'\b(we|our|us|wij|onze|ons|nous|notre|nos)\b', c, re.I):
        return False
    if re.match(r'^[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜ][A-Za-z0-9\-\séèëïàâôûùç]{1,40}\.\s+(Achieving|Reducing|Ensuring|Balancing|Measuring|Offsetting|Meaning|Referring|Supporting|Delivering|Providing|Creating|Building|Promoting|Protecting|Enabling|Improving|Defined|Involving|Covering|Bereiken|Verminderen|Zorgen|Compenseren|Betekent|Atteindre|Réduire|Assurer|Compenser|Signifie|Garantir)\b', c):
        return True
    third_party_actor=['the customer is responsible','the buyer is responsible','the supplier is responsible',
        'the client is responsible','you are responsible','your company must','you must ensure',
        'the customer must ensure','the customer must conduct','it is the customer','it is the buyer',
        'it is the supplier','de klant is verantwoordelijk','de koper is verantwoordelijk','de leverancier is verantwoordelijk',
        'u bent verantwoordelijk','le client est responsable',"l'acheteur est responsable",'le fournisseur est responsable',
        'vous êtes responsable']
    if any(p in c.lower() for p in third_party_actor):
        return True
    return False

def _v55_claim_context_ok(excerpt, trigger, dimension):
    c=_normalize_apostrophes((excerpt or '').lower()); trig=(trigger or '').lower()
    # v73: a blanket 25-character minimum previously rejected short-but-material claims
    # (badges, headings, slogans -- e.g. "We respect human rights." at 24 chars). The more
    # targeted checks below (nav-context exclusion, bare-title detection, and the <=5-word
    # claim-object-word check) already distinguish navigation/heading text from genuine short
    # claims, so the absolute-length floor is dropped in favour of that grammar/context logic.
    if not c.strip():
        return False
    if _looks_like_toc_or_index(excerpt):
        return False
    if _looks_like_impersonal_non_claim(excerpt):
        return False
    # v77: a negation immediately around the matched trigger flips it into the opposite of a
    # claim ("These components are NOT recyclable materials", "NOT all suppliers comply with
    # our code yet") -- nothing elsewhere in this function checks for negation, so both examples
    # were previously flagged as ordinary affirmative claims. Only look in a short window around
    # the trigger itself (not the whole excerpt) so a negation modifying an unrelated clause
    # elsewhere in a longer sentence doesn't suppress a genuine, separate claim.
    trig_pos=c.find(trig)
    if trig_pos != -1:
        # v84: two real gaps found in this window's negation matching. (1) "\bn't\b" requires a
        # word boundary BEFORE "n", but a real contraction glues the "n" onto the previous letter
        # ("isn't", "aren't", "doesn't", "wasn't", "can't", "won't") -- there is no boundary
        # there, so the pattern never matched any actual contraction, only a spelled-out "not".
        # (2) French elides "ne" to "n'" before any vowel-initial verb -- "n'est pas", "n'a pas"
        # -- which is the default form for "etre" (est/etaient/...), the single most common
        # claim-adjacent verb; "\bne\b" alone missed it entirely. Also added the bare English
        # "no" (mirroring Dutch "geen", already present) and widened the window slightly for
        # ordinary hedging clauses between the negation and the trigger.
        neg_before=c[max(0,trig_pos-70):trig_pos]
        neg_after=c[trig_pos+len(trig):trig_pos+len(trig)+35]
        # v87: two more real gaps. (1) clause-boundary leak -- "We do not believe in empty
        # promises; our packaging is 100% recyclable" wrongly suppressed the SECOND clause's
        # genuine claim, because the flat 70-char window reached back across the semicolon into
        # an unrelated clause's negation. Truncate the before-window to start after the nearest
        # preceding clause boundary, so only the current clause is checked. (2) French "ne...pas"
        # wraps the VERB, so when the trigger IS the negated adjective/object itself ("n'est
        # PAS 100% recyclable"), "pas" sits BEFORE the trigger too, not only after it -- the
        # previous version only ever looked for "pas" in the AFTER window, so this extremely
        # common, unambiguous negation was never caught. Check both windows for the pas-family.
        last_boundary=max(neg_before.rfind(';'),neg_before.rfind('.'),neg_before.rfind('!'),neg_before.rfind('?'))
        if last_boundary != -1:
            neg_before=neg_before[last_boundary+1:]
        fr_negator=re.search(r"\bne\b|\bn'",neg_before)
        fr_pas=re.search(r'\b(pas|jamais|plus|aucun|aucune)\b',neg_before) or re.search(r'\b(pas|jamais|plus|aucun|aucune)\b',neg_after)
        if re.search(r"\b(not|never|no)\b|n't|niet|geen|nooit",neg_before) or (fr_negator and fr_pas):
            return False
        # v87: a conditional/hypothetical sentence ("If our packaging were fully recyclable, it
        # would reduce waste", "Should we become carbon neutral, we would be proud") is not an
        # assertion that the current state is already true -- nothing else in this function
        # checks sentence mood. Requires an "if"/"should we" marker AND a subjunctive helper
        # ("would"/"were"/"could") together in the window around the trigger (either order,
        # since the conditional clause can come before or after the claim clause), not just
        # "if" alone, to avoid firing on an unrelated "if you have questions..." aside.
        cond_window=neg_before+' '+neg_after
        if (re.search(r'\bif\b',cond_window) and re.search(r'\b(would|were|could)\b',cond_window)) or \
           re.search(r'\bshould (we|our|they)\b',cond_window) or re.search(r'\bwere (we|our|they) to\b',cond_window):
            return False
    # v57e: previously this rejected ANY excerpt merely containing one of these phrases
    # anywhere, with no length check -- so a genuine claim sentence immediately following a
    # document heading in the same "sentence" (very common in PDF-extracted text, which often
    # loses the line break between a heading like "Sustainability Report 2025" and the body
    # text that follows it) was silently discarded along with real nav/title boilerplate.
    # Nav links and bare titles are short; a full claim sentence is not, so gate on length.
    if any(x in c for x in V55_NAV_CONTEXT_EXCLUSIONS) and len(c.split()) <= 10:
        return False
    if _looks_like_bare_document_title(c):
        return False
    # v74: PDF text extraction often glues a page header/footer -- company address, VAT/IBAN/
    # SWIFT registration details, phone/fax numbers -- directly onto the document title and
    # opening line with no line break, so a trigger like "supplier code" matches purely because
    # it is the document's own title, wrapped in letterhead boilerplate that survived
    # _looks_like_bare_document_title's short/clean-title check. Company registration/banking
    # details can never themselves be a sustainability claim, so reject on sight when at least
    # two such markers are present, regardless of excerpt length.
    letterhead_markers=['iban','swift','vat/tva','btw/tva','rpr/rpm','registered office',
        'company registration number','trade register','kvk','handelsregister']
    if sum(1 for m in letterhead_markers if m in c) >= 2:
        return False
    # Exclude headings that have no claim object.
    if len(c.split()) <= 5 and not any(x in c for x in ['product','packaging','material','supplier','sourcing','rights','wage','community','recycled','recyclable','net zero','carbon',
        'product','verpakking','materiaal','leverancier','rechten','loon','gemeenschap','gerecycleerd','recycleerbaar','koolstof',
        'produit','emballage','matériau','fournisseur','droits','salaire','communauté','recyclé','recyclable','carbone']):
        return False
    if 'challenges' in c and 'opportunities' in c:
        return False
    # v57m: statements that describe what a law/regulation/SDG requires, or what "living wage",
    # "fair wages" or "decent work" mean in general (citations, statistics, definitions,
    # references to an SDG or ILO convention) are not first-person company claims, even when
    # they happen to contain "we"/"our" only in an industry-wide or advocacy sense.
    definitional_citation=['according to','research shows','research suggests','studies show','study shows',
        'data shows','is estimated at','is defined as','refers to','supports un sustainable development goal',
        'sustainable development goal','sdg 8','ilo convention','csddd requires','csrd requires','the law requires',
        'regulation requires','directive requires','is a fundamental part of']
    if any(n in c for n in definitional_citation) and not any(x in c for x in ['we ensure','we guarantee','we comply','we are compliant','our compliance','we achieve','we have achieved']):
        return False
    # v84: "our industry" only caught that exact phrase; a very common equivalent phrasing --
    # an industry-wide/sector-wide statistic with no claim about the scanned company itself,
    # e.g. "The industry average is 30% recycled content" -- has neither "we/our/us" nor "our
    # industry" and slipped through untouched.
    if any(n in c for n in ['our industry','industry average','industry-wide average','sector average','sector-wide average']) and not any(x in c for x in ['we ensure','we guarantee','we comply','our operations','our supply chain','our products','our business']):
        return False
    # v84: a claim the company is merely REPORTING that a third party said (a supplier, a
    # certifier, a customer) is not the company's own assertion -- but the only existing guard
    # for this (third_party_context, below) is disabled by the mere presence of "we/our/us",
    # which is almost always present in a normal attribution sentence ("Our supplier told us
    # their packaging is recyclable"). Check for explicit reported-speech markers independent of
    # pronoun presence, unless paired with the company's own first-person assurance.
    # v87: this previously excluded on ANY of these reporting-verb phrases, but "CEO Jane Smith
    # STATED THAT our packaging is fully recyclable" or "the company CLAIMS THAT its supply
    # chain is fully audited and all suppliers comply" use the exact same ordinary reporting
    # verbs for the COMPANY'S OWN official voice -- these were wrongly suppressed as if they
    # were third-party attribution. Requiring a third-party role word ANYWHERE in the excerpt
    # isn't enough either -- a genuine "all suppliers comply" claim inherently mentions
    # "suppliers" too, just as the OBJECT of the company's own claim, not the subject doing the
    # telling. Only exclude when the third-party role word appears immediately BEFORE the
    # specific reporting phrase (i.e. actually acting as its grammatical subject, "Our SUPPLIER
    # told us...") rather than anywhere else in the sentence.
    reported_speech=['told us','informed us','told them','said their','claims that','stated that','assured us',
        'vertelde ons','meldde ons','verzekerde ons','nous a dit','nous a informé','nous a assuré']
    third_party_roles=['supplier','vendor','buyer','distributor','wholesaler',
        'leverancier','groothandel','distributeur',
        'fournisseur','grossiste','distributeur']
    for _rs_phrase in reported_speech:
        _rs_pos=c.find(_rs_phrase)
        if _rs_pos==-1:
            continue
        if any(r in c[max(0,_rs_pos-30):_rs_pos] for r in third_party_roles) and not any(
                x in c for x in ['we ensure','we guarantee','we confirm','we verified','we independently']):
            return False
    # v86: a passage reporting CRITICISM or an ALLEGATION against the company (e.g. "Critics
    # said the company falsely advertised the product as eco-friendly", found via the crawler's
    # own news/press-page candidates) was flagged as if "eco-friendly" were the company's own
    # claim -- it is the opposite, a description of criticism about the company. Excluded unless
    # the company is actually rebutting/denying the allegation in the same passage.
    criticism_context=['critics said','critics say','critics claim','critics have said','accused of','was accused',
        'were accused','accused the company','was criticized for','was criticised for','was sued for','was fined for',
        'falsely advertised','falsely marketed','falsely claimed','falsely marketing','alleged that','allegedly',
        'greenwashing lawsuit','greenwashing complaint','regulators found','watchdog found','investigation found',
        'critici zeiden','critici stellen','beschuldigd van','werd beschuldigd','aangeklaagd wegens','ten onrechte adverteerde',
        'les critiques ont dit','accusé de','accusée de','poursuivi pour','a été accusé','faussement annoncé','faussement présenté']
    # v87: the rebuttal exception only covered outright DENIAL ("we deny", "we reject") -- but a
    # company admitting past criticism while stating what it does NOW ("We were previously
    # accused of greenwashing and have since made our climate-neutral claims fully third-party
    # verified") isn't denying anything; it's making a genuine, CURRENT substantiation claim
    # that should still be evaluated. Added a present/perfect-tense current-claim signal as a
    # second, independent exception alongside outright denial.
    current_claim_signal=['have since','has since','we have since','now fully','are now','have made','have improved',
        'have addressed','have corrected','have fixed','hebben sindsdien','hebben inmiddels','nous avons depuis']
    if any(n in c for n in criticism_context) and not any(x in c for x in ['we deny','we reject','we dispute','we strongly disagree','this is false','the allegation is incorrect']) and not any(y in c for y in current_claim_signal):
        return False
    # v84: an interrogative sentence ("Is our packaging recyclable?", a genuine FAQ heading) is
    # a question, not an assertion -- the bare trigger words fire regardless of sentence type.
    if c.rstrip().endswith('?') and not any(x in c for x in ['we ensure','we guarantee','we confirm','yes,','yes ']):
        return False
    # v57j: bare legal-requirement triggers ("required by law", "legal requirement", "meets
    # legal requirements") fire on ANY mention of a legal obligation, not just one presented as
    # an environmental benefit -- e.g. "As required by law, our annual report is published every
    # March" has nothing to do with the environment. EmpCo Annex I point 10a specifically targets
    # presenting a legal requirement as a distinctive *environmental/sustainability* feature, so
    # require an environmental-topic word nearby for the generic (non-environment-qualified)
    # triggers. Triggers that already bake in "environmental"/"eu"/"regulation" (e.g. "compliant
    # with environmental law", "eu compliant") are left as-is since they are inherently on-topic.
    bare_legal_triggers=['meets legal requirements','according to legal standards','required by law','legal requirement']
    if trig in bare_legal_triggers and not any(x in c for x in ['environment','emission','chemical','substance','packaging','plastic','waste','energy','ecodesign','reach ','recycl','sustainab','carbon','climate']):
        return False
    # v57j: absolute safety wording ("zero accidents", "zero harm") combined with clear
    # forward-looking goal/target language is a stated ambition, not a claim that the outcome has
    # already been achieved (e.g. "Our safety goal for 2027 is zero accidents across all our
    # distribution centres"). Exclude unless paired with achieved-outcome language.
    safety_absolute=['zero accidents','zero harm','injury free','no workplace injuries']
    goal_language=['goal for','goal is','target for','target is','aim to','aims to','aspire','objective is','by 20','ambition']
    achieved_language=['achieved','have had','has had','recorded','maintained','delivered','since 20','to date','this year we']
    if any(n in c for n in safety_absolute) and any(g in c for g in goal_language) and not any(a in c for a in achieved_language):
        return False
    # v57j: describing that a policy/code document "covers" certain topics or "is available for
    # download/on request" is a meta-reference to a document's existence and scope, not an
    # operational assurance claim about the topics themselves (e.g. "Our Supplier Code of Conduct
    # is available for download and covers labour rights, health and safety").
    document_meta=['is available for download','available for download','is available on request',
        'available on request','can be downloaded','available to download','download our']
    if any(n in c for n in document_meta) and not any(sig in c for sig in ASSERTION_SIGNALS):
        return False
    # v57j: naming a specific, recognised third-party or public-authority certification scheme is
    # the opposite of the "self-declared sustainability label" risk EmpCo targets (Annex I point
    # 2a; Recital 7 explicitly lists the EU Ecolabel and EMAS as legitimate, publicly-established
    # schemes). Do not flag a label reference when a recognised scheme is explicitly named.
    recognised_schemes=['eu ecolabel','ecolabel logo','emas','regulation (ec) no 66/2010','regulation (ec) no 1221/2009',
        'nordic swan','blue angel','fairtrade certified','fair trade certified','gots certified','oeko-tex',
        'cradle to cradle','forest stewardship council','fsc certified','iso 14024','certified b corporation',
        'b corp certified','rainforest alliance certified']
    if dimension == 'green' and any(s in c for s in recognised_schemes):
        return False
    # v57j: a claim-trigger phrase inside a job posting/hiring context describes a role title or
    # responsibility, not a performance claim about the company's own products or operations
    # (e.g. "We are hiring a Climate Neutral Program Manager to lead our decarbonisation
    # roadmap" is a vacancy, not a claim that the company is climate neutral).
    hiring_context=['we are hiring','we\'re hiring','now hiring','job vacancy','join our team as',
        'apply for the role','open position','open positions','we are looking for a','we are recruiting']
    if any(n in c for n in hiring_context):
        return False
    # v57g: excerpts that discuss or report on a topic in general/industry terms -- rather than
    # making a first-person statement about the scanned company's own products or operations --
    # are not claims about this company (e.g. "The panel discussed what carbon neutral
    # certification schemes require for retailers" or "Read about zero waste initiatives
    # happening across the industry"). Generic and applies to both dimensions. Only excludes when
    # there is no first-person-plural anchor ("we"/"our"/"us"), so a genuine first-person claim
    # framed alongside industry context is still retained.
    third_party_context=['the panel discussed','panel discussion','according to experts','industry reports show',
        'industry report found','the debate about','debate over','conference discussed','article explains',
        'experts say','analysts say','critics argue','research suggests','study found','survey found',
        'across the industry','industry-wide','other brands','other companies','competitors',
        'happening across','trend in the industry']
    has_first_person=bool(re.search(r'\b(we|our|us|wij|we|ons|onze|nous|notre|nos)\b', c))
    if any(x in c for x in third_party_context) and not has_first_person:
        return False
    # v57f: describing that staff/teams are trained or educated ON a topic is a capacity-building
    # statement, not a claim that the company's products or operations already achieve the
    # performance being trained on (e.g. "we train our teams on sustainability matters... thanks
    # to the Sustainable Fashion School initiative" is not itself an environmental performance
    # claim). Applies to both dimensions since the same pattern occurs for social topics too
    # (e.g. "staff receive human rights training"). Exclude unless paired with an actual
    # product/outcome assertion, not just the training-topic name.
    training_context=['train our team','train our teams','train our staff','train our employees',
        'trains our team','trains our teams','trains our staff','trains our employees',
        'staff training','employee training','team training','training programme','training program',
        'we train','trains employees','trains staff','training on ','training in ','educate our team',
        'educate our staff','educate our employees']
    if any(n in c for n in training_context) and not any(x in c for x in ['our product','our products','have achieved','has achieved','results in','has resulted','resulted in','reduced by','increase of','decrease of','certified','certification','100%','all of our','all our']):
        return False
    if dimension == 'green':
        if trig in ['green','eco','sustainable','natural','ecological','ethical','responsible','fair'] and not any(x in c for x in ['product','products','packaging','material','materials','collection','range','choice','fashion','sourcing','sourced','made','designed','shop','buy','recycled','recyclable','climate','carbon','emissions','environmental']):
            return False
        # v75: "more sustainable"/"duurzamer"/"plus durable" alone is ambiguous -- English/Dutch/
        # French "sustainable"/"duurzaam"/"durable" routinely means "financially durable" or
        # "can be maintained long-term" with no environmental content at all ("a more sustainable
        # approach to managing debt", "duurzamer pensioenstelsel", "modèle plus durable pour
        # l'entreprise"). Require the same nearby product/environmental-context anchor as the bare
        # single-word triggers above before treating it as a green claim.
        if trig in ['more sustainable','duurzamer','plus durable','plus durables'] and not any(x in c for x in ['product','products','packaging','material','materials','collection','range','choice','fashion','sourcing','sourced','made','designed','shop','buy','recycled','recyclable','climate','carbon','emissions','environmental','milieu','klimaat','koolstof','verpakking','materiaal','materialen','environnement','emballage','matériau','matériaux']):
            return False
        # v77: same request-vs-completed-state distinction as the social supplier_request guard
        # below, applied to green wording -- "We encourage our suppliers to switch to recycled
        # packaging by 2027" is a governance request/ambition, not an assurance that the recycled
        # packaging is already in use.
        green_request_language=['encourage our suppliers','encourage suppliers','ask our suppliers','ask suppliers',
            'invite our suppliers','request our suppliers','moedigen onze leveranciers aan','vragen onze leveranciers',
            'encourageons nos fournisseurs','demandons à nos fournisseurs']
        if any(r in c for r in green_request_language) and not any(x in c for x in ['have achieved','has achieved','already use','already using','now use','now using','since 20','to date','100% of our suppliers','all of our suppliers']):
            return False
        # v57g: same principles/policy meta-description pattern as social claims below, applied
        # to green wording (e.g. "sets out our approach to climate action" describes a document,
        # it does not assert an achieved environmental outcome).
        green_meta=['sets out our approach','set out our approach','sets out the approach','outlines our approach',
            'describes our approach','explains our approach','covers our approach']
        if any(n in c for n in green_meta) and not any(sig in c for sig in ASSERTION_SIGNALS):
            return False
    if dimension == 'social':
        neutral=['backing british suppliers','supporting local suppliers','working with suppliers','become a supplier','supplier portal','list of suppliers']
        if any(n in c for n in neutral) and not any(x in c for x in ['responsible','ethical','audited','certified','traceable','due diligence','human rights','forced labour','forced labor','modern slavery','comply','compliance','standard','code']):
            return False
        # v73/v74: bare negation phrasing ("there is no forced labour", "no discrimination is
        # practised") is standard ILO/ETI Base Code policy-definition wording -- the Base Code's
        # nine clauses (freely-chosen employment, no child labour, safe working conditions, no
        # discrimination, no harsh/inhumane treatment, etc.) are reproduced near-verbatim in the
        # vast majority of supplier codes of conduct, and are policy statements, not marketing or
        # product assurance claims. Applies to every bare "no X"/"zero X" trigger across the
        # social claim lists, not just the forced/child-labour ones originally found -- the same
        # pattern showed up for "no discrimination" in a real scan. Require explicit
        # product/brand assurance language before treating the bare negation as a claim;
        # affirmative forms ("forced labour free", "free from forced labour") are a different,
        # unaffected trigger and remain flagged as before.
        bare_negation_triggers=['no forced labour', 'no forced labor', 'no child labour', 'no child labor',
            'no discrimination', 'zero discrimination', 'no workplace injuries', 'no pay gap', 'zero pay gap']
        if trig in bare_negation_triggers and not any(
                x in c for x in ['our product', 'our products', 'this product', 'these products', 'guarantee', 'certified', 'certificat']):
            return False
        # A supplier self-assessment questionnaire item ("[ ] your company has an external
        # responsible sourcing audit...") is a checkbox criterion the SUPPLIER must confirm about
        # ITSELF, addressed in the second person -- not a first-person claim by the scanned
        # company. Reject when the excerpt is clearly addressed to "your company"/"your
        # organisation" and lacks a first-person claim anchor.
        if re.search(r'\byour (company|organisation|organization|business|facility|factory)\b', c) and not re.search(r'\b(we|our|us)\b', c):
            return False
        # "We ASK all our suppliers to sign our code / share theirs with us" is a modest
        # governance request, not an assurance that suppliers actually comply -- it must not be
        # treated the same as "all suppliers ARE audited/certified/compliant". The word "code"
        # alone is too generic a safety-net (it also appears in "Supplier Code of Conduct" as a
        # document name), so this needs its own check independent of the broader neutral-phrase
        # gate above.
        supplier_request=['ask all our suppliers','ask our suppliers','we ask suppliers','request suppliers to','encourage suppliers to','invite suppliers to','suppliers to sign','suppliers to share','share theirs with us']
        if any(r in c for r in supplier_request) and not any(
                x in c for x in ['audited','certified','compliant','comply','compliance rate','% of suppliers','verified','signed by','have signed']):
            return False
        # The bare trigger "supplier code" matches purely because it is the document's own title
        # (e.g. "The Puratos Supplier Code of Conduct. In everything we do, we aim to be close to
        # people... to our suppliers...") -- a generic mission-statement preamble glued to a
        # title by PDF extraction, not an assurance claim about supplier coverage. Require a real
        # coverage/audit signal before accepting a bare "supplier code" mention as a claim; a
        # qualified form like "supplier code compliance" or "certified against our supplier code"
        # already implies more and is left untouched.
        if trig in ('supplier code', 'supplier code of conduct', 'supplier standards') and not any(
                x in c for x in ['all suppliers','100% of suppliers','audited','certified','compliant','comply',
                                  'compliance','due diligence','tier 1','tier 2','corrective action']):
            return False
        # v57f/v57g: sentences that describe what a charter, code of conduct or set of principles
        # SAYS, "sets out" or is "underpinned by" are meta-descriptions of a governance document's
        # content, not first-person operational assurance that the company actually delivers on
        # it (e.g. "They define the principles... and are underpinned by respect for human and
        # labour rights" or "The policy sets out our approach to human rights due diligence"
        # describe what a document contains, not an audited outcome). Exclude unless paired with
        # a genuine operational assertion signal.
        principles_meta=['define the principle','define our principle','defines the principle','defines our principle',
            'set out the principle','set out our principle','sets out the principle','sets out our principle',
            'govern our relation','governs our relation','govern the relation','governs the relation',
            'are underpinned by','is underpinned by','these principles','our values include',
            'sets out our approach','set out our approach','sets out the approach','outlines our approach',
            'describes our approach','explains our approach','covers our approach']
        if any(n in c for n in principles_meta) and not any(sig in c for sig in ASSERTION_SIGNALS):
            return False
    return True

def social_specification_check(claim_type, claim_text):
    c=(claim_text or '').lower(); t=(claim_type or '').lower()
    specificity_terms=['%','audit','audited','certified','certification','scope','tier 1','tier 2','due diligence',
                        'grievance','remediation','remediated','traceab','methodology','assessment','assessed',
                        'according to','standard','iso','sa8000','third-party','independent','kpi','baseline','policy',
                        'audit','geauditeerd','gecertificeerd','certificering','reikwijdte','zorgvuldigheidsplicht',
                        'klachtenmechanisme','herstelmaatregel','traceerbaar','methodologie','beoordeling','beoordeeld',
                        'volgens','norm','onafhankelijk','nulmeting','beleid',
                        'audité','certifié','certification','périmètre','devoir de vigilance',
                        'mécanisme de plainte','mesure corrective','traçable','méthodologie','évaluation','évalué',
                        'selon','norme','indépendant','année de référence','politique']
    has_specific=any(x in c for x in specificity_terms) or bool(re.search(r'\b\d{1,3}(?:[.,]\d+)?\s?%\b', c))
    if is_placeholder_finding(t):
        return {'status':'Not applicable','comment':'No material social claim was detected.'}
    if has_specific:
        return {'status':'Partly specified','comment':'Some substantiation indicators (e.g. audit, certification, scope, %) were found, but coverage, methodology and remediation should still be verified.'}
    if any(x in t for x in ['forced','modern slavery','supply','supplier','human rights','labour','labor']):
        return {'status':'Likely insufficient','comment':'The detected wording implies assurance or coverage but the retained passage shows no visible scope, audit basis, methodology or remediation evidence.'}
    return {'status':'Needs review','comment':'The claim should be checked for precise scope, evidence and remediation basis.'}

def social_blacklisted_indicator(claim_type, trigger, claim_text):
    t=(claim_type or '').lower(); trig=(trigger or '').lower()
    if 'forced' in t or 'modern slavery' in t:
        return ('Forced-labour product/supply-chain exposure and substantiation flag: wording implying products, suppliers or the supply chain are free from forced labour creates '
                'substantiation exposure under general UCPD misleading-claims rules today, and evidence of traceability, risk assessment, mitigation and remediation may become relevant to '
                'enforcement under Regulation (EU) 2024/3015 once its core provisions apply (14 December 2027). Article 1(3) of that Regulation confirms it does not itself create a standalone '
                'due-diligence obligation -- it is a product-market-access and customs-enforcement regime, not a claims law. This is a readiness/substantiation signal, not a finding that the '
                'Regulation has been breached.')
    if 'supply' in t or 'supplier' in t:
        return 'Potential red flag if supplier-coverage or audit wording (e.g. "all suppliers", "audited", "certified") is not backed by disclosed tier coverage, audit methodology and corrective-action closure rates.'
    if 'human rights' in t or 'labour' in t or 'labor' in t:
        return 'Potentially misleading social claim if human-rights/labour wording is not backed by a disclosed due-diligence process, grievance mechanism and remedy evidence. Social characteristics fall under EmpCo Art. 6(1)(b) but, unlike specific environmental Annex I practices, are assessed case-by-case rather than via a fixed blacklist.'
    return 'No direct regulatory-blacklist indicator identified, but claim-specific substantiation is still required.'

def social_ready_to_use_rewrite(claim_type):
    """Literal, fill-in-the-blank example rewrite for social/forced-labour claim types --
    see green_ready_to_use_rewrite() for the rationale. Bracketed placeholders mark facts only
    the company can supply; nothing inside them is invented or assumed true."""
    t=(claim_type or '').lower()
    if is_placeholder_finding(t):
        return ''
    if 'forced' in t or 'modern slavery' in t:
        return ('"Our forced-labour risk-management approach for [product/supply chain] includes [specific traceability '
                 'mechanism], [named risk-assessment methodology] and a documented remediation process, most recently '
                 'reviewed on [date]. Full policy: [link]."')
    if 'supply' in t or 'supplier' in t or 'sourcing' in t:
        return ('"[X%] of [named tier, e.g. Tier 1] suppliers, covering [X%] of [product category] sourcing, were '
                 'audited against [named standard, e.g. amfori BSCI] in [year], with [X] corrective actions closed. Full '
                 'data: [link]."')
    if 'human' in t or 'labour' in t or 'labor' in t:
        return ('"Our human-rights due-diligence process for [scope] includes [salient-risk assessment method], a '
                 'grievance channel at [link/contact], and remedy commitments reviewed [frequency]. Latest review: [date]."')
    if 'safety' in t or 'welfare' in t or 'health' in t:
        return ('"[Facility/operation] recorded [X] incidents per [X hours worked] in [year], tracked via [named '
                 'safety-management system], audited by [auditor/method]. [State any exclusions]."')
    if 'diversity' in t or 'inclusion' in t or 'equality' in t:
        return ('"[X%] of [role level, e.g. leadership positions] are held by [group], as of [date], measured via '
                 '[methodology]. Full breakdown: [link]."')
    if 'aspirational' in t or 'future' in t:
        return ('"Since [baseline year], we have achieved [specific measured outcome], and are working towards '
                 '[specific target] by [year], tracked via [named KPI/report]."')
    if 'community' in t or 'social-impact' in t or 'social impact' in t:
        return ('"In [year], our [named programme] reached [X specific beneficiaries/communities] in [named location], '
                 'measured by [named indicator/methodology]. Full report: [link]."')
    return ('"[Specific, verifiable statement], based on [methodology/standard/date], covering [exact scope]. Full '
            'evidence: [link]."')

def enrich_social_finding(f, trigger=''):
    f['regulatory_signal']=social_blacklisted_indicator(f.get('type',''), trigger, f.get('claim',''))
    # Social/human-rights characteristics are not covered by a fixed EmpCo Annex I blacklist entry
    # (unlike the specific environmental practices in points 2a/4a/4b/4c/10a) -- they are always
    # assessed case-by-case under general UCPD rules, so this is explicitly False here.
    f['blacklisted_practice_indicator']=False
    f.update(classify_legal_basis(f))
    f['specification_check']=social_specification_check(f.get('type',''), f.get('claim',''))
    f['ready_to_use_rewrite']=social_ready_to_use_rewrite(f.get('type',''))
    f['pre_publication_decision']='Do not publish/reuse without legal/compliance and evidence review.' if f.get('risk')=='High' and not is_placeholder_finding(f.get('type','')) else 'Can normally proceed only after standard evidence and wording review.'
    return f

def _v55_add_finding(fs, seen, text, trig, typ, risk, issue, rewrite, dimension, score):
    excerpt=_v55_sentence_list(text, trig)
    # v57n: "VISUAL CLAIM CUE: " is an internal marker prepended during HTML parsing to feed
    # image alt-text / aria-label / CSS-class values (e.g. a leaf icon's alt text) into claim
    # detection. It is a useful detection signal but was leaking verbatim into the "exact claim
    # passage" shown to reviewers, reading like a raw debug artifact rather than quoted page
    # content. Strip it from the displayed excerpt; the underlying detected wording is unaffected.
    if 'VISUAL CLAIM CUE: ' in excerpt:
        excerpt=re.sub(r'\s*VISUAL CLAIM CUE:\s*', ' ', excerpt).strip()
        excerpt=re.sub(r'\s+', ' ', excerpt)
    if not _v55_claim_context_ok(excerpt, trig, dimension):
        return
    sig=(typ, excerpt[:160].lower())
    if sig in seen:
        return
    seen.add(sig)
    # v57g: name the exact phrase that triggered detection explicitly, separate from the
    # generic category description in `issue`. Reviewers should never have to guess which
    # words in a longer excerpt caused the flag.
    why_flagged=f'This passage was flagged because it contains the wording "{trig}", matching the "{typ}" pattern.'
    if dimension == 'green':
        f={'dimension':'green','type':typ,'risk':risk,'claim':excerpt,'issue':issue,'rewrite':rewrite,'claim_score':score,
           'matched_phrase':trig,'why_flagged':why_flagged,
           'standards':['EmpCo / Directive (EU) 2024/825','UCPD misleading commercial practices'],
           'action':'Substantiate the green claim with scope, objective evidence, method, limits, same-medium specification and verification.',
           'problematic_terms':problematic_terms_for_finding(excerpt,typ)}
        fs.append(enrich_green_finding(f,trig))
    else:
        f={'dimension':'social','type':typ,'risk':risk,'claim':excerpt,'issue':issue,'rewrite':rewrite,'claim_score':score,
           'matched_phrase':trig,'why_flagged':why_flagged,
           'standards':standards_for_claim(typ),'action':'Substantiate the social claim with scope, evidence, reporting period, limitations and remediation/traceability where relevant.',
           'problematic_terms':problematic_terms_for_finding(excerpt,typ)}
        fs.append(enrich_social_finding(f,trig))

def detect_green_claims(text):
    low=_normalize_apostrophes((text or '').lower()); fs=[]; seen=set()
    # 1) direct / high-priority taxonomy from previous versions
    for triggers,typ,risk,issue,rewrite in GREEN_CLAIMS:
        hits=0
        for trig in triggers:
            if _trigger_present(trig, low):
                excerpt=_v55_sentence_list(text,trig)
                if typ=='Future environmental-performance claim' and not _looks_like_future_environmental_claim(excerpt):
                    continue
                score=74 if typ in ['Climate-neutrality or offsetting claim','Sustainability label / certification claim','Generic environmental claim','Legal requirement presented as green benefit'] else (68 if risk=='High' else 40)
                _v55_add_finding(fs, seen, text, trig, typ, risk, issue, rewrite, 'green', score)
                hits += 1
                if hits >= 3: break
    # 2) additional claim-like patterns that are often missed by exact blacklist terms
    for typ,risk,triggers,issue,rewrite in V55_GREEN_EXTRA_PATTERNS:
        hits=0
        for trig in triggers:
            if _trigger_present(trig, low):
                score=62 if risk=='Medium' else 68
                _v55_add_finding(fs, seen, text, trig, typ, risk, issue, rewrite, 'green', score)
                hits += 1
                if hits >= 3: break
    # 3) v73: percentage-based recycled-content claims ("made with 50% recycled plastic",
    # "contains 30% recycled content") use an arbitrary number, so a fixed trigger phrase can
    # never match them -- a small regex catches the pattern regardless of the exact percentage.
    hits=0
    for rx in (_PERCENT_RECYCLED_RE, _PERCENT_RECYCLED_NL_RE, _PERCENT_RECYCLED_FR_RE):
        for m in rx.finditer(text or ''):
            if hits >= 3: break
            _v55_add_finding(fs, seen, text, m.group(0), 'Recycled / recyclable material claim', 'Medium',
                              'Recycled, recyclable or circular-material wording can be a sustainability claim where conditions, percentage, certification, local recyclability or material scope are unclear.',
                              'State the recycled content percentage, material scope, certification or chain-of-custody basis, and practical recyclability conditions.',
                              'green', 62)
            hits += 1
    fs=sorted(fs,key=lambda f:f.get('claim_score',0), reverse=True)[:12]
    if not fs:
        fs.append(enrich_green_finding({'dimension':'green','type':'No material problematic green claim retained','risk':'Low','claim':'No exact problematic green claim was retained from the reviewed material.','issue':'The scan did not retain a direct EmpCo blacklisted-practice indicator or high-sensitivity environmental claim. General sustainability context is not scored as a problematic claim unless it contains specific claim wording.','rewrite':'No rewrite is needed unless the company wants to make a specific environmental claim.','claim_score':8,'standards':['General green-claim quality review'],'action':'Keep environmental claims specific, scoped and evidence-backed.','problematic_terms':[]},''))
    return fs

def detect_claims(text):
    low=_normalize_apostrophes((text or '').lower()); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        hits=0
        for trig in triggers:
            if _trigger_present(trig, low):
                excerpt=_v55_sentence_list(text,trig)
                if not _social_claim_context(excerpt, typ, trig, text):
                    continue
                score=76 if typ=='Forced-labour product or supply-chain claim' else (62 if risk=='High' else 40)
                _v55_add_finding(fs, seen, text, trig, typ, risk, issue, rewrite, 'social', score)
                hits += 1
                if hits >= 3: break
    for typ,risk,triggers,issue,rewrite in V55_SOCIAL_EXTRA_PATTERNS:
        hits=0
        for trig in triggers:
            if _trigger_present(trig, low):
                score=74 if 'Forced-labour' in typ else (62 if risk=='High' else 38)
                _v55_add_finding(fs, seen, text, trig, typ, risk, issue, rewrite, 'social', score)
                hits += 1
                if hits >= 3: break
    fs=sorted(fs,key=lambda f:f.get('claim_score',0), reverse=True)[:12]
    if not fs:
        fs.append({'dimension':'social','type':'No material problematic social claim retained','risk':'Low','claim':'No exact problematic social claim was retained from the reviewed material.','issue':'The scan did not retain a material high-risk social claim. Neutral references to suppliers, people, communities or employees are not scored unless they imply assurance, control, full coverage, certification, traceability, due diligence, forced-labour assurance or other high-stakes social performance.','rewrite':'No rewrite is needed unless the company wants to make a specific social-performance claim.','claim_score':8,'standards':['General claim-quality review'],'action':'Keep any future social claims specific, scoped and evidenced.','problematic_terms':[]})
    return fs

def _score_cap(material, external_score, regulatory_signal=False):
    n=len(material)
    if n==0:
        return 20 if external_score < 40 else 30
    # Conservative but not so restrictive that multiple claim signals disappear from score relevance.
    if n==1 and external_score < 40:
        return 56 if regulatory_signal else 44
    if n==2 and external_score < 40:
        return 62 if regulatory_signal else 52
    if n<=4 and external_score < 40:
        return 70 if regulatory_signal else 62
    if external_score < 40:
        return 76
    return 92

def _recalibrated_score(material, substantiation, evidence_notes, external_score, sector_score, regulatory_signal=False, audience_factor=1.0):
    if not material:
        raw=round((8*0.45 + 15*0.30 + external_score*0.15 + sector_score*0.10)*audience_factor)
        return min(raw, _score_cap(material, external_score, regulatory_signal))
    top=max(f.get('claim_score',0) for f in material)
    blacklisted=sum(1 for f in material if f.get('blacklisted_practice_indicator') or 'forced-labour' in f.get('type','').lower() or 'climate-neutrality' in f.get('type','').lower())
    count_factor=min(20, 4*max(0,len(material)-1))
    claim_wording=min(100, top + count_factor + 5*blacklisted)
    evidence_gap=max(0,100-substantiation)
    # v88: claim-wording severity carried only 42% of the blended score, so even a MAXED-OUT
    # claim_wording_risk (100/100, e.g. multiple EmpCo Annex I blacklisted-practice claims) could
    # still land in "Low" territory once evidence-gap/external/sector -- which are frequently
    # near-zero in an ordinary scan with no external controversy -- diluted it. Raised claim
    # wording's weight; evidence-gap and external stayed at roughly their prior ratio to each
    # other, sector (the least specific signal) absorbed most of the reduction.
    raw=round((claim_wording*0.50 + evidence_gap*0.22 + external_score*0.20 + sector_score*0.08)*audience_factor)
    cap=_score_cap(material, external_score, regulatory_signal or blacklisted>0)
    return max(0,min(100,min(raw,cap)))

# Override excerpt extraction with a sentence-segmentation approach to avoid mixing several claims.

# Final excerpt refinement: keep only the claim sentence when it is readable.
def _v55_sentence_list(text, trigger, window=850):
    raw=' '.join((text or '').replace('\r',' ').replace('\n','. ').split())
    trig=(trigger or '').lower()
    if not raw or not trig:
        return raw[:620]
    parts=[p.strip() for p in re.split(r'(?<=[.!?])\s+', raw) if p.strip()]
    for idx,p in enumerate(parts):
        if trig in p.lower():
            out=p
            # v57f: a sentence that is grammatically "complete" by punctuation alone can still
            # read as an unclear fragment if it opens mid-thought -- e.g. "(BAT) Guide, which
            # contains detailed information..." gives no indication of what BAT stands for or
            # what is actually being claimed. Detect common fragment-start patterns (lowercase
            # opening, a leading parenthesis, or a dangling relative clause / conjunction with no
            # subject) and pull in the previous sentence so the reviewer can see the actual claim.
            starts_like_fragment=bool(re.match(r'^[a-z(]', out)) or bool(re.match(r'^(which|that|who|whom|and|but|or)\b', out, re.IGNORECASE))
            # v57n: only pull in the previous "sentence" if it actually looks like prose context
            # (e.g. "our Best Available Techniques") -- not if it is itself PDF title/index
            # clutter such as "33Puratos 2025 Sustainability Report GRI Introduction Appendix"
            # glued together by page-number and heading concatenation. Prepending that kind of
            # text made the excerpt harder to read, not clearer.
            if starts_like_fragment and idx>0 and not _looks_like_toc_or_index(parts[idx-1]):
                out=parts[idx-1]+' '+out
            if len(out) < 25 and idx+1 < len(parts):
                out=out+' '+parts[idx+1]
            # v57n: joining sentence fragments can leave a doubled sentence-ending punctuation
            # mark (e.g. "...conventional practices.." or "...forward..") -- collapse to one.
            out=re.sub(r'([.!?])\1+', r'\1', out)
            return out[:620]
    i=raw.lower().find(trig)
    if i < 0:
        return raw[:620]
    return raw[max(0,i-180):min(len(raw),i+300)][:620]


# -----------------------------
# V60 EXTERNAL PUBLIC-SOURCE SIGNALS
# -----------------------------
# Generic recall/precision improvements for regulator, NGO, union, litigation and
# reputable-media signals. The previous implementation could lose relevant results
# because (1) only three narrow queries were run, (2) it stopped after the first search
# provider returned anything, (3) stakeholder status had to be stated literally in the
# snippet, and (4) an external article could be misclassified as company-owned merely
# because it discussed a company's sustainability report or policy.

EXTERNAL_SIGNAL_MAX_QUERIES=max(4,min(8,int(os.environ.get('EXTERNAL_SIGNAL_MAX_QUERIES','6'))))
EXTERNAL_SIGNAL_RESULTS_PER_QUERY=max(4,min(10,int(os.environ.get('EXTERNAL_SIGNAL_RESULTS_PER_QUERY','6'))))
EXTERNAL_SIGNAL_WORKERS=max(2,min(6,int(os.environ.get('EXTERNAL_SIGNAL_WORKERS','4'))))
EXTERNAL_SEARCH_ALL_PROVIDERS=os.environ.get('EXTERNAL_SEARCH_ALL_PROVIDERS','1').strip().lower() not in {'0','false','no','off'}

_V60_CORPORATE_WORDS={'group','company','companies','holding','holdings','international','global','corporation','corp','inc','limited','ltd','plc','sa','nv','bv','srl','llc','ag','se','the','gmbh'}
_V60_OFFICIAL_HOST_MARKERS=(
    '.gov','.gouv.','europa.eu','ec.europa.eu','commission.europa.eu','agcm.it','acm.nl',
    'cma.gov.uk','ftc.gov','asa.org.uk','jep.be','oecd.org','ilo.org','ohchr.org',
    'bund.de','autoritedelaconcurrence.fr','economie.gouv.fr','competition-policy.ec.europa.eu',
    'nclc.gov','nlrb.gov','justice.gov','parliament.uk','senat.fr','assemblee-nationale.fr'
)
_V60_NGO_HOST_MARKERS=(
    'business-humanrights.org','antislavery.org','amnesty.','hrw.org','humanrightswatch.org',
    'cleanclothes.org','publiceye.ch','chinalaborwatch.org','workersrights.org','remake.world',
    'changingmarkets.org','greenpeace.org','clientearth.org','duh.de','oxfam.','fairwear.org',
    'labourbehindthelabel.org','ethicalconsumer.org','somo.nl','banktrack.org','globalwitness.org'
)
_V60_MEDIA_HOST_MARKERS=(
    'reuters.com','apnews.com','bbc.','theguardian.com','ft.com','bloomberg.com','politico.',
    'euractiv.','lemonde.fr','dw.com','cnn.com','nytimes.com','washingtonpost.com','esgdive.com',
    'esgtoday.com','thefashionlaw.com','businessoffashion.com','supplychaindive.com'
)
_V60_UNION_HOST_MARKERS=('union','workers','labour','labor','tradeunion','aflcio','ituc-csi','industriall-union')

_V60_GREEN_NEGATIVE=(
    'greenwashing','misleading environmental','misleading green','misleading sustainability',
    'deceptive environmental','unsubstantiated environmental','vague environmental','false environmental',
    'environmental claims investigation','environmental claim complaint','sustainability claims investigation',
    'fine','fined','penalty','sanction','ban','prohibited','complaint','lawsuit','court','investigation',
    'probe','watchdog','regulator','authority','advertising standards','net-zero claim','net zero claim',
    'carbon neutral claim','climate neutral claim','accused','alleged','criticism','criticised','criticized'
)
_V60_SOCIAL_NEGATIVE=(
    'social washing','forced labour','forced labor','child labour','child labor','modern slavery',
    'labour rights','labor rights','worker rights','workers rights','human rights abuse','human rights concern',
    'exploitation','exploitative','excessive overtime','underpaid','wage theft','unsafe working',
    'working conditions','union busting','discrimination','harassment','complaint','lawsuit','court',
    'investigation','probe','fine','fined','penalty','sanction','strike','union','protest','boycott',
    'breach','violation','misconduct','accused','alleged','allegation','criticism','criticised','criticized'
)
_V60_ENFORCEMENT_TERMS=('investigation','probe','complaint','lawsuit','court','fine','fined','penalty','sanction','ban','prohibited','settlement','decision','ruling','enforcement')
_V60_GREEN_ANCHORS=('greenwashing','environmental','sustainability claim','green claim','climate','carbon','net zero','net-zero','recyclable','recycled','circular','eco label','ecolabel')
_V60_SOCIAL_ANCHORS=('social washing','forced labour','forced labor','child labour','child labor','modern slavery','labour','labor','worker','human rights','working conditions','wage','union','discrimination','supply chain')


def _v60_host(result):
    return (urlparse((result or {}).get('url','')).hostname or '').lower().removeprefix('www.')


def _v60_host_matches_marker(host, marker):
    """Boundary-aware host/marker match. A raw `marker in host` substring check let an
    unrelated host that merely CONTAINS a marker (e.g. "notagcm.it" contains "agcm.it",
    "verbund.de" contains "bund.de", "networkers.com" contains "workers") get classified as a
    Government/regulator, media or union source it isn't, inheriting that source type's higher
    credibility rating undeservedly.

    v87 fix: the v84 fix bounded markers with a dot on only one side (".gov", "amnesty.") with
    `re.search`, which finds the dot-bounded fragment ANYWHERE in the host, not just at a
    plausible domain-suffix position -- ".gov" still matched inside
    "fake-cma.gov.uk.evil.com", and "amnesty." still matched inside
    "news.amnesty.org.phish.ru", because both are legitimately dot-bounded fragments that just
    happen to have more (attacker-controlled) domain structure tacked on afterward. Rewritten
    on host LABELS: the marker's own labels must appear as a contiguous run within the host's
    labels, followed by at most one further label (a plausible bare TLD, e.g. "org" after
    "amnesty", or "fr" after "gouv") -- not an arbitrary number of additional labels that would
    mean the REAL registrable domain is something else entirely.
    """
    if not host or not marker:
        return False
    if '.' not in marker:
        # No dot anywhere (e.g. "union", "workers") -- a bare word makes no domain-suffix/prefix
        # claim, so a simple word-boundary substring match is right.
        return bool(re.search(r'(?<![a-z0-9])'+re.escape(marker)+r'(?![a-z0-9])', host))
    core=marker.strip('.')
    if not core:
        return False
    host_labels=host.split('.')
    core_labels=[l for l in core.split('.') if l]
    n=len(core_labels)
    if n==0 or n>len(host_labels):
        return False
    for i in range(len(host_labels)-n+1):
        if host_labels[i:i+n]!=core_labels:
            continue
        tail=host_labels[i+n:]
        # A bare TLD tail ("org" after "amnesty", "fr" after "gouv") is fine. A two-label tail
        # is only fine when it's a recognised compound ccTLD shape (e.g. "co.uk", "org.uk",
        # "com.au") -- an arbitrary two-label tail like "notreal.io" or "fake.ru" means the
        # REAL registrable domain is something else entirely, tacked on after the marker.
        if len(tail)<=1:
            return True
        if len(tail)==2 and tail[0] in {'co','com','org','net','gov','ac'} and len(tail[1])==2:
            return True
    return False


def _v60_source_kind(result):
    host=_v60_host(result)
    text=_external_signal_text(result)
    if any(_v60_host_matches_marker(host,m) for m in _V60_OFFICIAL_HOST_MARKERS) or host.endswith('.gov') or '.gov.' in host:
        return 'Government / regulator'
    if any(_v60_host_matches_marker(host,m) for m in _V60_NGO_HOST_MARKERS):
        return 'NGO / civil society'
    if any(_v60_host_matches_marker(host,m) for m in _V60_UNION_HOST_MARKERS) or any(x in text for x in ['trade union','workers union','labour union','labor union']):
        return 'Union / worker organisation'
    if any(_v60_host_matches_marker(host,m) for m in _V60_MEDIA_HOST_MARKERS):
        return 'Press / investigative media'
    if any(x in text for x in ['court','lawsuit','legal action','class action','complaint filed']):
        return 'Legal / complaint'
    if host.endswith('.edu') or '.ac.' in host or 'university' in text or 'research institute' in text:
        return 'Academic / research'
    return 'Other public source'


def _v65_strip_accents(value):
    """Transliterate accented letters instead of deleting them: the [^a-z0-9] stripping used
    throughout this file's name-normalisation helpers only recognises plain ASCII, so an
    accented company name like "L'Oréal" collapsed the "é" into a bare separator (norm
    "l or al", compact "loral") rather than "loreal" -- a false-negative source for matching
    French/Dutch company names against their own domains."""
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(c))


def _v60_company_terms(company_name):
    raw=re.sub(r'\s+',' ',_v65_strip_accents(company_name or '').lower()).strip()
    # v77: "&" between short brand initials (H&M, M&S, C&A, P&G) is part of the brand itself.
    # Treating it as a generic separator like the substitution below does for every other
    # punctuation character splits these into meaningless single letters ("h", "m"), which then
    # fail the length>=3 filter just below and degrade the whole brand query to "h m". Join
    # across it instead -- but only when both sides are short (initials), not for a genuine
    # multi-word "X & Y" name like "Procter & Gamble", where joining would erase the real word
    # boundary and produce one unsearchable mega-token.
    raw=re.sub(r'\b([a-z0-9]{1,2})\s*&\s*([a-z0-9]{1,2})\b',r'\1\2',raw)
    phrase=re.sub(r'[^a-z0-9]+',' ',raw).strip()
    tokens=[t for t in phrase.split() if len(t)>=3 and t not in _V60_CORPORATE_WORDS]
    compact=''.join(tokens)
    return phrase,tokens,compact






def _v62_term_present(text, term):
    """Match controversy terms as complete words/phrases, not substrings."""
    term=(term or '').strip().lower()
    if not term:
        return False
    pattern=r'(?<![a-z0-9])'+re.escape(term).replace(r'\ ',r'\s+')+r'(?![a-z0-9])'
    return re.search(pattern,text or '',flags=re.I) is not None


def _v62_clean_external_content(value):
    text=re.sub(r'\s+',' ',str(value or '')).strip()
    if not text:
        return ''
    noise=('an official website of','a .gov website','banner featuring','learn more button',
           'cookie policy','accept cookies','all rights reserved','subscribe to our newsletter')
    parts=[p.strip() for p in re.split(r'(?<=[.!?])\s+',text) if p.strip()]
    kept=[p for p in parts if not any(n in p.lower() for n in noise)]
    return ' '.join(kept or parts)[:420]








def source_credibility(result):
    kind=_v60_source_kind(result)
    if kind=='Government / regulator': return 'High'
    if kind in {'NGO / civil society','Union / worker organisation','Press / investigative media'}: return 'Medium-high'
    if kind in {'Legal / complaint','Academic / research'}: return 'Medium'
    text=_external_signal_text(result)
    if any(x in text for x in ['blog','forum','opinion','linkedin.com','facebook.com','instagram.com','youtube.com']): return 'Low'
    return 'Medium'


def _v60_signal_score(result, company_name, dimension='social'):
    hits,enforcement,kind,accepted=_v60_negative_strength(result,dimension)
    if not accepted:
        return -999
    kind_weight={
        'Government / regulator':48, 'NGO / civil society':42,
        'Union / worker organisation':40, 'Press / investigative media':35,
        'Legal / complaint':30, 'Academic / research':22, 'Other public source':12
    }.get(kind,12)
    title=(result.get('title','') or '').lower()
    company_phrase=_v60_company_terms(company_name)[0]
    company_bonus=14 if company_phrase and company_phrase in title else 5
    provider_score=result.get('score',0) or 0
    try: provider_bonus=min(10,max(0,float(provider_score)*10))
    except Exception: provider_bonus=0
    return kind_weight + min(24,hits*6) + min(10,enforcement*4) + company_bonus + provider_bonus


def _v60_canonical_url(url):
    p=urlparse(url or '')
    host=(p.hostname or '').lower().removeprefix('www.')
    path=re.sub(r'/+$','',p.path or '/')
    return host+path










def _v60_run_queries(queries):
    allr=[]; attempts=[]; providers=set(); seen=set()
    queries=list(dict.fromkeys(q for q in queries if q))[:EXTERNAL_SIGNAL_MAX_QUERIES]
    def _one(q):
        return q,search_public_sources(q,EXTERNAL_SIGNAL_RESULTS_PER_QUERY)
    with ThreadPoolExecutor(max_workers=min(EXTERNAL_SIGNAL_WORKERS,len(queries) or 1)) as pool:
        futures=[pool.submit(_one,q) for q in queries]
        for fut in as_completed(futures):
            q,(res,atts)=fut.result()
            attempts.extend([dict(a,query=q) for a in atts])
            for r in res:
                key=_v60_canonical_url(r.get('url',''))
                if key and key not in seen:
                    item=dict(r); item['query']=q; item['credibility']=source_credibility(item)
                    allr.append(item); seen.add(key)
                    if item.get('provider'): providers.add(item['provider'])
    return allr,attempts,providers,queries


def _v60_social_queries(company,findings=None):
    quoted='"'+str(company).replace('"','')+'"'
    base=[
        f'{quoted} forced labour labor workers NGO report',
        f'{quoted} labour rights working conditions union investigation',
        f'{quoted} human rights supply chain complaint lawsuit regulator',
        f'{quoted} social washing misleading social claims criticism',
    ]
    for theme in query_themes_from_findings(findings or []):
        base.append(f'{quoted} {theme}')
    return list(dict.fromkeys(base))


def _v60_green_queries(company,findings=None):
    quoted='"'+str(company).replace('"','')+'"'
    base=[
        f'{quoted} greenwashing environmental claims regulator fine investigation',
        f'{quoted} misleading sustainability claims complaint watchdog',
        f'{quoted} environmental claims NGO criticism',
        f'{quoted} climate claim net zero carbon neutral challenge',
    ]
    for theme in green_query_themes(findings or []):
        base.append(f'{quoted} {theme}')
    return list(dict.fromkeys(base))







# -----------------------------
# V63 EXTERNAL SIGNAL RECALL + DIAGNOSTICS
# -----------------------------
# V63 addresses false negatives where well-documented regulator, NGO, union and
# investigative-media signals were not retained. The main causes were overly long
# search queries, exact singular/plural matching, and a company-owned-domain test
# that could reject independent sites merely because the brand appeared in the host.

_V63_SOCIAL_EXPLICIT = (
    'social washing','forced labour','forced labor','child labour','child labor','modern slavery',
    'labour rights','labor rights','worker rights','workers rights','workers\' rights',
    'human rights abuse','human rights abuses','human rights concern','human rights concerns',
    'labour exploitation','labor exploitation','worker exploitation','workers exploitation',
    'illegal working hours','excessive working hours','long working hours','low wages',
    'piecework wages','unsafe working conditions','poor working conditions','union busting'
)
_V63_SOCIAL_ANCHORS = (
    'labour','labor','worker','workers','workforce','working hours','working conditions',
    'wage','wages','overtime','factory','factories','supplier','suppliers','supply chain',
    'human rights','trade union','union','child labour','child labor','forced labour','forced labor'
)
_V63_SOCIAL_NEGATIVE = (
    'investigation','investigating','probe','inquiry','report reveals','report finds','exposed',
    'accused','alleged','allegation','allegations','criticism','criticised','criticized',
    'concern','concerns','violation','violations','breach','breaches','illegal','exploitative',
    'exploitation','abuse','abuses','underpaid','unsafe','risk','risks','complaint','complaints',
    'lawsuit','court','fine','fined','penalty','sanction','strike','protest','boycott',
    'overstate','overstates','overstated','overclaim','overclaims','overclaimed',
    'exaggerate','exaggerates','exaggerated','downplay','downplays','downplayed'
)
_V63_GREEN_EXPLICIT = (
    'greenwashing','misleading environmental claim','misleading environmental claims',
    'misleading green claim','misleading green claims','deceptive environmental claim',
    'deceptive environmental claims','unsubstantiated environmental claim',
    'unsubstantiated environmental claims','false environmental claim','false environmental claims',
    'environmental claim complaint','environmental claims complaint',
    'environmental claim investigation','environmental claims investigation','misleading sustainability claim','misleading sustainability claims',
    'sustainability claim investigation','sustainability claims investigation'
)
_V63_GREEN_ANCHORS = (
    'environmental','green','climate','carbon','emission','emissions','sustainability','sustainable',
    'net zero','net-zero','climate neutral','carbon neutral','recyclable','recycled','recycling',
    'circular','eco','ecological','evolushein','fossil fuel','fossil-fuel'
)
_V63_GREEN_NEGATIVE = (
    'misleading','deceptive','vague','generic','omissive','unsubstantiated','false',
    'investigation','investigating','probe','inquiry','complaint','watchdog','regulator','authority',
    'fine','fined','penalty','sanction','prohibited','ban','accused','alleged','allegation',
    'criticism','criticised','criticized','contradicted','contradiction','violation','violations',
    'overstate','overstates','overstated','overclaim','overclaims','overclaimed',
    'exaggerate','exaggerates','exaggerated','downplay','downplays','downplayed'
)
_V63_STAKEHOLDER_SITE_QUERIES = {
    'green': (
        'site:agcm.it {q}',
        'site:commission.europa.eu {q} environmental claims',
        'site:ec.europa.eu {q} sustainability claims',
        'site:reuters.com {q} greenwashing',
        'site:theguardian.com {q} greenwashing',
        'site:business-humanrights.org {q} environmental claims',
    ),
    'social': (
        'site:business-humanrights.org {q}',
        'site:publiceye.ch {q} workers',
        'site:chinalaborwatch.org {q}',
        'site:antislavery.org {q}',
        'site:reuters.com {q} child labour workers',
        'site:theguardian.com {q} working conditions',
    ),
}


def _v63_any(text, terms):
    return any(_v62_term_present(text, t) for t in terms)


def _v60_negative_strength(result, dimension='social'):
    """V63 polarity test with plural/variant coverage and source-aware acceptance."""
    text=_external_signal_text(result)
    kind=_v60_source_kind(result)
    recognised=kind!='Other public source'
    enforcement=[t for t in _V60_ENFORCEMENT_TERMS if _v62_term_present(text,t)]
    if dimension=='green':
        explicit=[t for t in _V63_GREEN_EXPLICIT if _v62_term_present(text,t)]
        anchors=[t for t in _V63_GREEN_ANCHORS if _v62_term_present(text,t)]
        negative=[t for t in _V63_GREEN_NEGATIVE if _v62_term_present(text,t)]
    else:
        explicit=[t for t in _V63_SOCIAL_EXPLICIT if _v62_term_present(text,t)]
        anchors=[t for t in _V63_SOCIAL_ANCHORS if _v62_term_present(text,t)]
        negative=[t for t in _V63_SOCIAL_NEGATIVE if _v62_term_present(text,t)]
    # Accept explicit controversy language directly. Otherwise require a thematic anchor
    # plus enforcement/negative language. Recognised stakeholder sources need only one
    # clear negative marker; unknown sources need stronger corroborating wording.
    accepted=bool(explicit) or (
        bool(anchors) and (
            bool(enforcement) or
            (recognised and bool(negative)) or
            len(negative)>=2
        )
    )
    strength=len(explicit)*3 + len(anchors) + len(negative) + len(enforcement)
    return strength,len(enforcement),kind,accepted








def _v63_company_query_names(company_name):
    raw=re.sub(r'\s+',' ',str(company_name or '')).strip()
    phrase,tokens,compact=_v60_company_terms(raw)
    names=[]
    # A short brand query generally has much better recall than a long legal entity name.
    if tokens:
        query_tokens=list(tokens)
        if len(query_tokens)>=3 and query_tokens[0] in {'bank','banco','banque'}:
            query_tokens=query_tokens[1:]
        names.append(' '.join(query_tokens[:2]))
        names.append(query_tokens[0])
    if phrase:
        names.append(phrase)
    if raw:
        names.append(raw)
    out=[]
    for n in names:
        n=re.sub(r'\s+',' ',n).strip(' "')
        if len(n)>=3 and n.lower() not in {x.lower() for x in out}:
            out.append(n)
    return out[:3] or [raw or 'company']


def _v63_primary_queries(company_name, dimension, findings=None):
    brand=_v63_company_query_names(company_name)[0]
    q='"'+brand.replace('"','')+'"'
    if dimension=='green':
        base=[
            f'{q} greenwashing',
            f'{q} misleading environmental claims',
            f'{q} environmental claims regulator',
            f'{q} sustainability claims fine investigation',
            f'{q} climate carbon emissions criticism',
            f'{q} eco sustainable claims complaint',
        ]
        themes=green_query_themes(findings or [])[:2]
    else:
        base=[
            f'{q} forced labor',
            f'{q} forced labour',
            f'{q} working conditions wages',
            f'{q} labor rights NGO report',
            f'{q} labour rights investigation',
            f'{q} child labor supplier',
        ]
        themes=query_themes_from_findings(findings or [])[:2]
    for theme in themes:
        base.append(f'{q} {theme}')
    return list(dict.fromkeys(base))


def _v63_fallback_queries(company_name, dimension):
    brand=_v63_company_query_names(company_name)[0]
    q='"'+brand.replace('"','')+'"'
    queries=[template.format(q=q) for template in _V63_STAKEHOLDER_SITE_QUERIES[dimension]]
    if dimension=='green':
        queries.extend([f'{q} vague misleading sustainability claims',f'{q} environmental marketing allegations'])
    else:
        queries.extend([f'{q} excessive working hours low wages',f'{q} supplier labour exploitation'])
    return list(dict.fromkeys(queries))


def _v63_search_dimension(company_name, findings, dimension):
    first_queries=_v63_primary_queries(company_name,dimension,findings)
    allr,attempts,providers,run_queries=_v60_run_queries(first_queries)
    ranked=_v60_rank_dedupe(allr,company_name,dimension,30)
    fallback_used=False
    if len(ranked)<2:
        fallback_used=True
        more,atts,provs,qs=_v60_run_queries(_v63_fallback_queries(company_name,dimension))
        attempts.extend(atts); providers.update(provs); run_queries.extend(qs)
        seen={_v60_canonical_url(r.get('url','')) for r in allr}
        for r in more:
            key=_v60_canonical_url(r.get('url',''))
            if key and key not in seen:
                allr.append(r); seen.add(key)
        ranked=_v60_rank_dedupe(allr,company_name,dimension,30)
    company_matched=sum(1 for r in allr if source_mentions_company(r,company_name))
    negative_candidates=sum(1 for r in allr if source_mentions_company(r,company_name) and (is_green_negative_source(r) if dimension=='green' else is_negative_external_source(r)))
    diagnostics={
        'raw_result_count':len(allr),
        'company_matched_count':company_matched,
        'negative_candidate_count':negative_candidates,
        'retained_count':len(ranked),
        'fallback_used':fallback_used,
        'providers_used':sorted(providers),
        'queries_run':list(dict.fromkeys(run_queries)),
    }
    return ranked,allr,attempts,providers,run_queries,diagnostics


def _v63_external_response(company, findings, dimension):
    configured=bool(TAVILY_API_KEY or (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX))
    themes=(green_query_themes(findings or []) if dimension=='green' else query_themes_from_findings(findings or []))
    if not configured:
        return {'enabled':False,'summary':'External public-source search is not enabled because neither TAVILY_API_KEY nor Google Custom Search credentials are configured.','results':[],'compact_sources':[],'providers_used':[],'provider_attempts':[],'query_themes':themes,'queries_run':[],'raw_result_count':0,'search_diagnostics':{'raw_result_count':0,'company_matched_count':0,'negative_candidate_count':0,'retained_count':0,'fallback_used':False,'providers_used':[],'queries_run':[]}}
    ranked,allr,attempts,providers,run_queries,diagnostics=_v63_search_dimension(company,findings,dimension)
    if ranked:
        summary=(summarise_green_ext(ranked) if dimension=='green' else summarise_ext(ranked))
    elif diagnostics['raw_result_count']:
        summary=(f"External search returned {diagnostics['raw_result_count']} result(s), but none passed all entity-match, external-ownership, negative-polarity and {dimension}-relevance checks. Manual review may still be appropriate.")
    else:
        summary='No external public-source result was returned by the configured providers.'
    if providers:
        summary+=' Search provider(s) used: '+', '.join(sorted(providers))+'.'
    return {'enabled':True,'summary':summary,'results':ranked,'compact_sources':compact_sources(ranked,5,dimension),'providers_used':sorted(providers),'provider_attempts':attempts,'query_themes':themes,'queries_run':list(dict.fromkeys(run_queries)),'raw_result_count':len(allr),'search_diagnostics':diagnostics}







# ---------------------------------------------------------------------------
# V64 ENTITY LOCK + INTERNAL CLAIM RECOVERY
# ---------------------------------------------------------------------------
# V64 fixes a coupled regression: a bare company name could be resolved to the
# first merely plausible search-result domain, and external results were accepted
# when the target company appeared only incidentally in a snippet. Once the wrong
# entity entered the pipeline, the crawler could review the wrong/blocked site and
# external signals could be about a competitor. The functions below keep one
# canonical entity and its official roots throughout resolution, crawling, claim
# detection and external-source filtering.

V64_CANONICAL_COMPANY_SITES={
    'shein':'https://www.shein.com',
    'shein group':'https://www.shein.com',
    'h&m':'https://www2.hm.com',
    'h & m':'https://www2.hm.com',
    'hm':'https://www2.hm.com',
    'zara':'https://www.zara.com',
    'inditex':'https://www.inditex.com',
}
V64_COMPANY_DOMAIN_ALIASES={
    'shein':{'shein.com','sheingroup.com'},
    'h&m':{'hm.com','hmgroup.com'},
    'zara':{'zara.com','inditex.com'},
    'inditex':{'inditex.com','zara.com'},
}
# Group/corporate sites often contain the substantive sustainability claims while
# the retail storefront is JavaScript-heavy or access-protected.
KNOWN_GROUP_DOMAINS.update({
    'shein':['https://www.sheingroup.com'],
    'sheingroup':['https://www.shein.com'],
    'hm.com':['https://hmgroup.com'],
    'www2.hm.com':['https://hmgroup.com'],
    'hmgroup':['https://www2.hm.com'],
})

V64_OTHER_BRANDS={
    'h&m','h & m','hm','zara','inditex','temu','primark','uniqlo','asos','boohoo',
    'nike','adidas','mango','gap','amazon','walmart','alibaba','forever 21','patagonia',
    'lidl','aldi','delhaize','tesco','carrefour','shein'
}
V64_GENERIC_HOST_LABELS={'www','www2','m','mobile','shop','store','group','global','corporate','official','eu','eur','us','uk',
    # v84: this app specifically targets NL/FR/Benelux companies -- without these, a company's
    # own localized domain (e.g. "brandnl.com", "brand-be.com") failed the is_company_owned_source
    # leftover-word check (the "nl"/"be" leftover matched neither this set nor
    # _V60_CORPORATE_WORDS) and was wrongly treated as a third-party source, feeding the
    # company's own content into the negative-external-signal pipeline instead of excluding it.
    # v87: "no"/"at"/"it" were removed from this v84 list -- they are also common short English
    # words, and "brand+no" is an established activism-domain naming convention (e.g. the real
    # "ShellNo" campaign). Confirmed exploitable: is_company_owned_source wrongly classified
    # "shell-no.com"/"shellno.org" as Shell's own domain, which would have silently excluded a
    # genuine critic site from the negative-external-signal pipeline -- the opposite of what
    # this leftover-word tightening was meant to achieve. The remaining codes (nl, be, fr, de,
    # es, ch, pt, dk, fi, se, ie, lu) don't double as common standalone English words the same
    # way, so they keep the original v84 fix's value for actually-relevant Benelux/EU markets.
    'nl','be','fr','de','es','ch','pt','dk','fi','se','ie','lu'}


def _v64_norm(value):
    return re.sub(r'[^a-z0-9]+',' ',_v65_strip_accents(value or '').lower()).strip()


def _v64_compact(value):
    return re.sub(r'[^a-z0-9]+','',_v65_strip_accents(value or '').lower())


def _v64_brand_aliases(company_name):
    raw=_v64_norm(company_name)
    tokens=[t for t in raw.split() if t not in _V60_CORPORATE_WORDS and len(t)>=2]
    aliases=[]
    if raw: aliases.append(raw)
    if tokens:
        aliases.append(' '.join(tokens))
        aliases.append(tokens[0])
        if len(tokens)>=2: aliases.append(' '.join(tokens[:2]))
    # Normalise common display/group names.
    if 'shein' in tokens: aliases.extend(['shein','shein group'])
    if ('h' in tokens and 'm' in tokens) or raw in {'hm','h m','h and m'}: aliases.extend(['h&m','h & m','hm','h m'])
    out=[]
    for a in aliases:
        n=_v64_norm(a)
        if len(n)>=2 and n not in out: out.append(n)
    return out


def _v64_alias_occurrences(text, aliases):
    n=_v64_norm(text)
    total=0
    hits=[]
    for alias in aliases:
        p=r'(?<![a-z0-9])'+re.escape(alias).replace(r'\ ',r'\s+')+r'(?![a-z0-9])'
        c=len(re.findall(p,n,flags=re.I))
        if c: hits.append(alias); total+=c
    return total,hits


def _v64_root_label(host):
    host=(host or '').lower().removeprefix('www.')
    parts=host.split('.')
    if len(parts)<2: return parts[0] if parts else ''
    # For country/locale subdomains, use the registrable brand label.
    return parts[-2]


def _v64_known_site(name):
    key=_v64_norm(name)
    if key in V64_CANONICAL_COMPANY_SITES:
        return V64_CANONICAL_COMPANY_SITES[key]
    compact=_v64_compact(key)
    for k,v in V64_CANONICAL_COMPANY_SITES.items():
        if _v64_compact(k)==compact:
            return v
    return None


# V72: removed a duplicate, unreachable `_v64_official_candidate_score` + `resolve_company_website`
# pair that used to live here. Python keeps only the last definition of a function in a module, so
# this copy was silently shadowed by the one further below (now the single source of truth) and
# never actually ran. See V72_CHANGELOG.md.




def _v64_negative_near_target(text,aliases,window=220):
    low=_v64_norm(text)
    negative_terms=list(_V63_SOCIAL_EXPLICIT)+list(_V63_SOCIAL_NEGATIVE)+list(_V63_GREEN_EXPLICIT)+list(_V63_GREEN_NEGATIVE)+list(_V60_ENFORCEMENT_TERMS)
    for alias in aliases:
        for m in re.finditer(r'(?<![a-z0-9])'+re.escape(alias).replace(r'\ ',r'\s+')+r'(?![a-z0-9])',low):
            segment=low[max(0,m.start()-window):m.end()+window]
            if any(_v62_term_present(segment,t) for t in negative_terms):
                return True
    return False


def _v64_primary_competitors_in_title(title,target_aliases):
    norm=_v64_norm(title)
    hits=[]
    for b in V64_OTHER_BRANDS:
        bn=_v64_norm(b)
        if not bn or bn in target_aliases: continue
        if re.search(r'(?<![a-z0-9])'+re.escape(bn).replace(r'\ ',r'\s+')+r'(?![a-z0-9])',norm):
            hits.append(b)
    return hits








def compact_sources(results,limit=6,dimension=None):
    out=[]
    for r in _dedupe_similar_sources(results or [])[:limit]:
        txt=_external_signal_text(r); kind=r.get('source_kind') or _v60_source_kind(r)
        manual=bool(r.get('manual_verified') or r.get('verified'))
        dim=dimension or r.get('dimension') or ('green' if is_green_negative_source(r) else 'social')
        url=r.get('url','') or ''; host=(urlparse(url).hostname or '').removeprefix('www.')
        score=r.get('_signal_score',0) or 0
        try: relevance='High' if float(score)>=70 else 'Medium'
        except Exception: relevance='Medium'
        out.append({'title':(r.get('title','') or '')[:170],'url':url,'source_name':host or kind,
            'content':_v62_clean_external_content(r.get('content',''))[:320],
            'category':kind,'source_kind':kind,'credibility':source_credibility(r),'provider':r.get('provider',''),
            'published_date':r.get('published_date','') or 'Date not available','status':_source_status(txt),
            'severity':_source_severity(txt),'review_status':'Verified' if manual else 'Retained — manual verification required',
            'entity_match':r.get('entity_match','Direct — target in source'),'entity_match_reason':r.get('entity_match_reason',''),
            'dimension':dim,'relevance':relevance,'polarity':'negative',
            'polarity_reason':r.get('_negative_reason','Explicit adverse event or criticism linked to the assessed company'),
            'related_claim_area':'Environmental claims' if dim=='green' else 'Social / labour claims',
            'related_articles_count':r.get('related_articles_count',1)})
    return out


def targeted_negative_sources(results,company_name,limit=5,reviewed_pages=None,negative_fn=None):
    dimension='green' if negative_fn is is_green_negative_source else 'social'
    eligible=[]
    for r in results or []:
        if is_company_owned_source(r,company_name,reviewed_pages): continue
        if not entity_match_details(r,company_name,reviewed_pages)['matched']: continue
        if not (negative_fn or is_negative_external_source)(r): continue
        eligible.append(r)
    ranked=_v60_rank_dedupe(eligible,company_name,dimension,max(limit*3,limit),reviewed_pages)
    return compact_sources(ranked,limit,dimension)




def _v64_external_response(company,findings,dimension,reviewed_pages=None):
    configured=external_search_configured()
    themes=(green_query_themes(findings or []) if dimension=='green' else query_themes_from_findings(findings or []))
    empty_diag={'raw_result_count':0,'company_matched_count':0,'negative_candidate_count':0,'retained_count':0,
                'fallback_used':False,'competitor_primary_rejected_count':0,'providers_used':[],'queries_run':[]}
    if not configured:
        return {'enabled':False,'summary':'External public-source search is not enabled because no search provider (TAVILY_API_KEY, SERPER_API_KEY, or GOOGLE_SEARCH_API_KEY+GOOGLE_SEARCH_CX) is configured.','results':[],'compact_sources':[],'providers_used':[],'provider_attempts':[],'query_themes':themes,'queries_run':[],'raw_result_count':0,'search_diagnostics':empty_diag}
    ranked,allr,attempts,providers,run_queries,diagnostics=_v64_search_dimension(company,findings,dimension,reviewed_pages)
    # An attempt can fail outright (provider error/timeout/quota) rather than simply return
    # zero results. Those are very different situations: a quota-exhausted or rate-limited
    # provider means the search never actually ran, which is not evidence of a clean record
    # and must not be reported the same way as "we searched and found nothing". Silently
    # treating the two identically was making the tool report a false clean bill of health
    # whenever the configured API keys hit a rate limit or usage cap.
    # v90: a provider can also come back 'skipped_cooldown' (this run already saw that
    # provider fail on quota/rate-limit grounds and skipped re-trying it) rather than
    # 'failed' outright. That is just as much "the search did not actually run" as a
    # live failure -- treating only 'failed' as disqualifying would silently let a
    # cooldown-skipped provider count as a clean, confirmed-empty result.
    search_failed=bool(attempts) and not any(a.get('status')=='ok' for a in attempts) and any(a.get('status') in ('failed','skipped_cooldown') for a in attempts)
    if ranked:
        summary=(summarise_green_ext(ranked) if dimension=='green' else summarise_ext(ranked))
    elif search_failed:
        error_examples=sorted({str(a.get('error') or '').strip() for a in attempts if a.get('status')=='failed' and a.get('error')})[:2]
        detail=(' Example error(s): '+'; '.join(error_examples)+'.') if error_examples else ''
        summary=('External public-source search could NOT be completed -- every provider request failed '
                  '(e.g. rate limit or usage quota reached), so this is not confirmation of a clean external '
                  f'record, only that the search did not run.{detail} Re-run the scan later or check the '
                  'configured API key/quota.')
    elif diagnostics['raw_result_count']:
        summary=f"External search returned {diagnostics['raw_result_count']} result(s), but none passed the direct-entity, external-ownership, negative-polarity and {dimension}-relevance checks."
    else:
        summary='No external public-source result was returned by the configured providers.'
    if diagnostics.get('competitor_primary_rejected_count'):
        summary+=f" {diagnostics['competitor_primary_rejected_count']} competitor-primary result(s) were excluded."
    if providers: summary+=' Search provider(s) used: '+', '.join(sorted(providers))+'.'
    return {'enabled':True,'summary':summary,'search_failed':search_failed,'results':ranked,'compact_sources':compact_sources(ranked,5,dimension),
        'providers_used':sorted(providers),'provider_attempts':attempts,'query_themes':themes,
        'queries_run':list(dict.fromkeys(run_queries)),'raw_result_count':len(allr),'search_diagnostics':diagnostics}


def external(company,findings=None,reviewed_pages=None):
    return _v64_external_response(company,findings,'social',reviewed_pages)


def external_green(company,findings=None,reviewed_pages=None):
    return _v64_external_response(company,findings,'green',reviewed_pages)





# ---------------------------------------------------------------------------
# V65 GENERIC ENTITY LOCK + DYNAMIC OFFICIAL-SITE DISCOVERY
# ---------------------------------------------------------------------------
# V64 solved the demonstrated SHEIN/H&M regression, but several safeguards still
# depended on brand-specific aliases and substring hostname matching. V65 makes the
# identity controls generic: the exact input/official domain remains authoritative,
# company-owned roots are matched exactly, body-only external matches require strong
# evidence, and related official sustainability sites can be discovered conservatively
# for any company when primary-site coverage is limited.

V65_CORPORATE_SUFFIXES=('group','holding','holdings','corp','corporation','company','global','plc','sa','nv','ag','se',
    'bv','gmbh','inc','ltd','llc','srl')
V65_RELATED_TERMS=('official','corporate','group','sustainability','responsibility','esg','annual report','impact report','investor relations')


def _v65_strip_corporate_suffix(label):
    value=_v64_compact(label)
    changed=True
    while changed and value:
        changed=False
        for suffix in V65_CORPORATE_SUFFIXES:
            if value.endswith(suffix) and len(value)>len(suffix)+2:
                value=value[:-len(suffix)]
                changed=True
                break
    return value


def _v65_scan_input_company_hint(raw, resolved_url=''):
    raw=re.sub(r'\s+',' ',str(raw or '')).strip()
    if raw and not looks_like_domain_or_url(raw):
        return raw
    host=(urlparse(resolved_url or norm_url(raw)).hostname or '').lower()
    label=_v64_root_label(host)
    stripped=_v65_strip_corporate_suffix(label) or _v64_compact(label)
    if stripped:
        known={'hm':'H&M','shein':'SHEIN'}
        return known.get(stripped, stripped.replace('-',' ').title())
    return ''


def _v65_brand_aliases(company_name, reviewed_pages=None):
    aliases=list(_v64_brand_aliases(company_name))
    for value in reviewed_pages or []:
        host=(urlparse(str(value)).hostname or '').lower()
        if not host:
            continue
        label=_v64_root_label(host)
        for candidate in (label, _v65_strip_corporate_suffix(label)):
            norm=_v64_norm(candidate)
            if len(norm)>=2 and norm not in aliases and norm not in V64_GENERIC_HOST_LABELS:
                aliases.append(norm)
    return aliases


def _v65_alias_compacts(company_name, reviewed_pages=None):
    return {_v64_compact(a) for a in _v65_brand_aliases(company_name,reviewed_pages) if len(_v64_compact(a))>=2}


def _v65_owned_roots(reviewed_pages=None):
    roots=set(company_owned_roots(reviewed_pages))
    for value in reviewed_pages or []:
        host=(urlparse(str(value)).hostname or '').lower()
        root=_root_domain(host)
        if root:
            roots.add(root)
    return roots


_V70_SECOND_LEVEL_SUFFIXES={'co','com','org','net','gov','ac'}
_V70_INDEPENDENT_DOMAIN_MARKERS=('watch','watchdog','justice','rights','campaign','critic','complaint','facts','union','workers',
    'sucks','boycott','scam','fraud','exposed','truth','leaks')


def _v70_domain_label(host):
    """Return the brand-bearing label, including common country-code domains."""
    labels=[part for part in str(host or '').lower().removeprefix('www.').split('.') if part]
    if len(labels)>=3 and len(labels[-1])==2 and labels[-2] in _V70_SECOND_LEVEL_SUFFIXES:
        return _v64_compact(labels[-3])
    return _v64_compact(labels[-2] if len(labels)>=2 else (labels[0] if labels else ''))


def is_company_owned_source(result, company_name, reviewed_pages=None):
    """Generic exact-domain ownership check.

    A watchdog domain such as ``brandwatch.org`` is not company-owned merely because
    the company name is a substring. Ownership is established from reviewed official
    roots, exact registrable-domain labels, or a company label plus a normal corporate
    suffix (for example ``brandgroup.com``).
    """
    host=_v60_host(result)
    if not host:
        return False
    root=_root_domain(host)
    if root and root in _v65_owned_roots(reviewed_pages):
        return True
    label=_v70_domain_label(host)
    aliases=_v65_alias_compacts(company_name,reviewed_pages)
    if label in aliases:
        return True
    for alias in aliases:
        if label in {alias+s for s in V65_CORPORATE_SUFFIXES}:
            return True
        # Treat brand-led microsites as first-party unless the domain clearly identifies an
        # independent watchdog, rights group, campaign or worker organisation. A raw
        # startswith/endswith previously accepted ANY leftover text -- so "notdelhaize.be" or
        # "delhaizesucks.com" (ends/starts with the alias, no independence marker present) were
        # wrongly treated as the company's own, silently dropping genuine lookalike/critic
        # sources from the negative-signals pipeline. Only accept the match when the leftover
        # part is itself a recognised generic/corporate word (shop, group, eu, official...), not
        # an arbitrary string.
        if len(alias)>=4:
            leftover=label[len(alias):] if label.startswith(alias) else (label[:-len(alias)] if label.endswith(alias) else None)
            if leftover and (leftover in V64_GENERIC_HOST_LABELS or leftover in _V60_CORPORATE_WORDS):
                if not any(marker in label for marker in _V70_INDEPENDENT_DOMAIN_MARKERS):
                    return True
    # Retain only exact verified domain aliases; never substring-match arbitrary hosts.
    key=_v64_norm(company_name)
    for brand,domains in V64_COMPANY_DOMAIN_ALIASES.items():
        if _v64_norm(brand)==key or _v64_compact(brand) in aliases:
            if root in domains:
                return True
    return False


def _v65_official_candidate_score(result, company_name):
    url=result.get('url','') or ''
    host=(urlparse(url).hostname or '').lower().removeprefix('www.')
    root=_root_domain(host)
    if not host or any(root==d or root.endswith('.'+d) for d in NON_OFFICIAL_SITE_DOMAINS):
        return -999
    aliases=_v65_brand_aliases(company_name)
    compacts={_v64_compact(a) for a in aliases if len(_v64_compact(a))>=3}
    label=_v64_compact(_v64_root_label(root or host))
    title=result.get('title','') or ''
    content=result.get('content','') or ''
    title_count,_=_v64_alias_occurrences(title,aliases)
    content_count,_=_v64_alias_occurrences(content,aliases)
    score=0
    known=_v64_known_site(company_name)
    known_root=_root_domain((urlparse(known).hostname or '')) if known else ''
    if known_root and root==known_root:
        score+=120
    if label in compacts or any(label==c+s for c in compacts for s in V65_CORPORATE_SUFFIXES):
        score+=80
    if title_count:
        score+=35
    if content_count:
        score+=min(18,content_count*6)
    relation=_v64_norm(title+' '+content)
    if any(term in relation for term in V65_RELATED_TERMS):
        score+=10
    # A result requires target evidence. A generic 'official' page is insufficient.
    if not (title_count or content_count or label in compacts):
        return -999
    return score


def _v72_extract_title(html):
    m=re.search(r'<title[^>]*>(.*?)</title>', html or '', re.I|re.S)
    return re.sub(r'\s+',' ', m.group(1)).strip() if m else ''

# Ordered from most to least preferred when several guessed domains all validate. Generic/
# flagship TLDs come first because multinational companies conventionally host their main
# global corporate site (with the richest sustainability/ESG content) there; country-code
# domains (.be, .nl, ...) are more often a thinner regional storefront for that one market.
_V72_DOMAIN_GUESS_TLDS=('.com','.eu','.net','.org','.co','.be')
_V72_TLD_PREFERENCE={tld:i for i,tld in enumerate(_V72_DOMAIN_GUESS_TLDS)}

def _v72_guess_domain_bases(name):
    """Plausible bare-domain name bases for a company, derived from the name alone --
    no external search API involved."""
    norm=_v64_norm(name)
    tokens=[t for t in norm.split() if t not in _V60_CORPORATE_WORDS and len(t)>=2]
    bases=[]
    compact=_v64_compact(name)
    if compact and len(compact)>=3:
        bases.append(compact)
    if tokens:
        joined=''.join(tokens)
        if joined and joined not in bases:
            bases.append(joined)
        if len(tokens[0])>=4 and tokens[0] not in bases:
            bases.append(tokens[0])
    # v89: a leading definite article ("Le Pain Cotidien", "La Redoute", "Het Financieele
    # Dagblad") was never stripped, so the ONLY base tried was e.g. "lepaincotidien" -- if the
    # real domain omits the article ("paincotidien.com"), it was never even attempted.
    # Reproduced: "Pain Cotidien" alone correctly generates a "paincotidien" candidate, but "Le
    # Pain Cotidien" does not, purely because "le" isn't in the stopword set the way English
    # "the" already is. Add the article-stripped form as an EXTRA candidate rather than
    # replacing the with-article one -- some brands genuinely keep the article in their real
    # domain (lecreuset.com), so both forms need to stay in play; validation against live page
    # content decides which one is actually correct.
    leading_articles=('le','la','les','de','het','the')
    norm_words=norm.split()
    if norm_words and norm_words[0] in leading_articles and len(norm_words)>1:
        stripped=' '.join(norm_words[1:])
        stripped_compact=_v64_compact(stripped)
        if stripped_compact and len(stripped_compact)>=3 and stripped_compact not in bases:
            bases.append(stripped_compact)
    return bases[:4]

def _v72_guess_domain_candidates(name):
    bases=_v72_guess_domain_bases(name)
    out=[]
    for base in bases:
        for tld in _V72_DOMAIN_GUESS_TLDS:
            out.append(f'https://www.{base}{tld}')
    return out[:14]

def _v72_validate_guessed_domain(url, name):
    """Fetch a guessed domain and confirm the company name actually appears on it, in the
    title or the page body. Uses _open_public_url directly (not the thinner fetch_html
    wrapper) so it can validate against the *final* URL after any redirect -- a guessed
    domain that redirects elsewhere must still name-match at its actual landing page, not
    just at the URL we guessed. Returns (final_url, content_length) when validated,
    otherwise None. This lets bare-name resolution work for any company with a
    conventional domain, without depending on a paid search API being configured."""
    try:
        # v90: was timeout=8 -- combined with _open_public_url's own 2-user-agent retry, a
        # single slow/unresponsive candidate could cost up to 16s on its own. Tightened so the
        # overall domain_guess_deadline in resolve_company_website() can't be overshot by much
        # even if the deadline check only happens between candidates, not during one.
        data,ctype,final_url=_open_public_url(url,timeout=5,
            accept='text/html,application/xhtml+xml;q=0.9,*/*;q=0.5',max_bytes=2500000)
    except Exception:
        return None
    if 'html' not in ctype:
        return None
    html=data.decode('utf-8',errors='ignore')
    if not html or len(html)<200:
        return None
    aliases=_v64_brand_aliases(name)
    compacts={_v64_compact(a) for a in aliases if len(_v64_compact(a))>=3}
    host=(urlparse(final_url or url).hostname or '').lower().removeprefix('www.')
    root_label=_v64_compact(_v64_root_label(host))
    if root_label not in compacts:
        return None
    title=_v72_extract_title(html)
    title_count,_=_v64_alias_occurrences(title,aliases)
    body_count,_=_v64_alias_occurrences(html[:6000],aliases)
    if title_count or body_count:
        return (final_url or url), len(html)
    return None

def resolve_company_website(name):
    """Resolve a bare company name to a website URL.

    V72: this used to be one of three duplicate definitions of this function in the file
    (Python only ever runs the last one -- see the V72_CHANGELOG for the cleanup). The active
    copy also used to raise a hard error whenever search confidence was below 70, which blocked
    the scan outright for any company outside the small known-site list whenever no confident
    search match was found -- including when no search provider was configured at all. This
    version restores the earlier, intentionally graceful degrade path (matching the tool's V63/
    V64 behaviour) and strengthens it with a credential-free domain-guess-and-validate step, so
    a bare company name resolves to *something* for any company, always with a clear confidence
    note attached rather than a hard failure.

    V72.1: the domain-guess step now evaluates every plausible candidate instead of stopping at
    the first one that validates, and prefers the flagship .com/.eu/.net/.org/.co domain over a
    country-code one (e.g. .be) when several validate -- otherwise a company whose regional site
    happens to answer faster/more reliably than its global site gets scanned on the thinner
    regional site instead of the main corporate one, which is exactly where the fuller
    sustainability/ESG content usually lives.
    """
    known=_v64_known_site(name)
    if known:
        host=urlparse(known).hostname or known
        return known, f'Company name "{name}" was resolved to the verified official domain {host}. Related official sustainability/group sites may also be checked when coverage is limited.'
    query=f'"{name}" official company website'
    results=[]
    # v91: these two calls used to bypass search_public_sources() entirely, so they never
    # benefited from the provider cooldown added there -- meaning a quota-exhausted Tavily/
    # Google account still paid full request+retry latency here on the FIRST search call of
    # EVERY single scan, before the cooldown from the crawl's own external-signal queries
    # could ever kick in. Checking/setting the same cooldown here closes that gap.
    if not _v90_provider_in_cooldown('Tavily'):
        try:
            a=tavily_search(query,max_results=6) or []
            for r in a: r.setdefault('provider','Tavily')
            results.extend(a)
        except Exception: _v90_note_provider_result('Tavily')
    if not _v90_provider_in_cooldown('Google Custom Search'):
        try:
            b=google_search(query,max_results=6) or []
            for r in b: r.setdefault('provider','Google Custom Search')
            seen={_v60_canonical_url(r.get('url','')) for r in results}
            results.extend(r for r in b if _v60_canonical_url(r.get('url','')) not in seen)
        except Exception: _v90_note_provider_result('Google Custom Search')
    ranked=sorted(((_v65_official_candidate_score(r,name),r) for r in results),key=lambda x:x[0],reverse=True)
    if ranked and ranked[0][0]>=70:
        host=(urlparse(ranked[0][1].get('url','')).hostname or '').lower()
        return f'https://{host}', f'Company name "{name}" was resolved to {host} after a strong brand/domain and title-content match. Verify the entity before relying on the result.'

    # No search provider configured, or no confidently-matched result: try every plausible
    # domain guess directly and accept only ones whose live page content actually names the
    # company. This keeps resolution working for companies with thin search coverage, or when
    # no Tavily/Google credentials are configured on this deployment, without silently
    # substituting the wrong company. When several validate, prefer the flagship gTLD over a
    # country-code domain, then the richer page (more content usually means the main corporate
    # site rather than a thin regional one).
    # v90: this loop had NO overall time budget -- each candidate can cost up to
    # len(BROWSER_USER_AGENTS)*8s (~16s) inside _open_public_url's own per-user-agent retry,
    # and up to 14 candidates are tried unconditionally (no early exit once one validates, by
    # design, so the flagship/highest-content domain can still be preferred over an earlier
    # weaker match). Reproduced directly: resolve_company_website('AB InBev') took 174 SECONDS
    # -- none of the 6 guessed candidates (abinbev.com/.eu/.net/.org/.co/.be) matched the real
    # domain (ab-inbev.com, with a hyphen) quickly, so several were slow/unresponsive and ate
    # their full per-candidate budget one after another. This is a completely separate time
    # sink from CRAWL_BUDGET_SECONDS, which only bounds the crawl that happens AFTER
    # resolution -- a scan can hang here before the crawl budget is ever reached. Cap the whole
    # guessing loop to a fixed deadline and stop trying further candidates once it's spent,
    # using whatever validated so far.
    domain_guess_deadline=time.time()+22
    validated=[]
    for candidate_url in _v72_guess_domain_candidates(name):
        if time.time()>=domain_guess_deadline:
            break
        result=_v72_validate_guessed_domain(candidate_url,name)
        if result:
            final_url,content_length=result
            tld='.'+urlparse(final_url).hostname.rsplit('.',1)[-1].lower()
            pref=_V72_TLD_PREFERENCE.get(tld,len(_V72_TLD_PREFERENCE))
            validated.append((pref,-content_length,final_url))
    if validated:
        validated.sort()
        best_url=validated[0][2]
        host=(urlparse(best_url).hostname or '').lower()
        extra=f' ({len(validated)} domain(s) matched; the flagship/highest-content one was preferred.)' if len(validated)>1 else ''
        return f'https://{host}', (f'Company name "{name}" was resolved to {host} by matching a guessed domain against its live '
                                     f'page content (no confident search-provider match was available).{extra} Verify the entity before relying on the result.')

    # Last resort: an unverified best-guess domain. The scan still proceeds -- a clearly
    # flagged low-confidence guess is more useful than blocking the scan outright -- but the
    # note makes plain that this was not independently confirmed.
    guess=f'https://www.{slugify_company_name(name)}.com'
    no_provider=not external_search_configured()
    provider_note=(' No external search provider is configured on this deployment (TAVILY_API_KEY / '
                    'SERPER_API_KEY / GOOGLE_SEARCH_API_KEY+GOOGLE_SEARCH_CX), so only the known-site list and direct '
                    'domain guesses could be tried.') if no_provider else ''
    return guess, (f'Company name "{name}" could not be confidently verified via search or a direct domain match.{provider_note} '
                    f'The scan used the unverified best-guess domain {guess} -- please confirm this is the correct company '
                    f'website; re-run with the exact URL if not.')


def infer_company(url,text,company_name_hint=''):
    """Generic host/input lock: page references to competitors cannot change entity."""
    hint=re.sub(r'\s+',' ',str(company_name_hint or '')).strip()
    if hint:
        key=_v64_norm(hint)
        for k,p in PROFILES.items():
            if _v64_norm(k)==key or _v64_compact(k)==_v64_compact(key):
                return {'company':p[0],'sector':p[1],'sector_risk':p[2],'context':p[3]}
        display=hint
    else:
        host=(urlparse(url).hostname or '').lower()
        label=_v64_root_label(host)
        base=_v65_strip_corporate_suffix(label) or _v64_compact(label)
        display={'hm':'H&M','shein':'SHEIN'}.get(base,base.replace('-',' ').title()) if base else ''
        for k,p in PROFILES.items():
            if _v64_compact(k) and _v64_compact(k)==base:
                return {'company':p[0],'sector':p[1],'sector_risk':p[2],'context':p[3]}
    if display:
        return {'company':display,'sector':'Sector not explicitly identified','sector_risk':'','context':'Company identity is anchored to the user input and reviewed official domain; mentions of other companies do not change the assessed entity.'}
    guessed=_guess_company_from_text(text)
    if guessed:
        return {'company':guessed,'sector':'Sector not explicitly identified','sector_risk':'','context':'Company name inferred from uploaded document text.'}
    return {'company':'Company reviewed','sector':'Sector not explicitly identified','sector_risk':'','context':'No company domain or reliable document name was available.'}


def _v65_first_alias_position(text, aliases):
    norm=_v64_norm(text)
    positions=[]
    for alias in aliases:
        m=re.search(r'(?<![a-z0-9])'+re.escape(alias).replace(r'\ ',r'\s+')+r'(?![a-z0-9])',norm)
        if m:
            positions.append(m.start())
    return min(positions) if positions else 10**9


def entity_match_details(result,company_name,reviewed_pages=None):
    """Conservative generic direct-entity match.

    Automatic retention requires the target in the title/URL. Body-only matches are
    accepted only when the target is prominent, repeated at least three times and the
    negative issue is stated close to the target. This prevents articles primarily about
    another company from leaking into any company's context, without relying on a fixed
    competitor list.
    """
    aliases=_v65_brand_aliases(company_name,reviewed_pages)
    title=result.get('title','') or ''
    content=result.get('content','') or ''
    url=result.get('url','') or ''
    title_count,_=_v64_alias_occurrences(title,aliases)
    content_count,_=_v64_alias_occurrences(content,aliases)
    url_count,_=_v64_alias_occurrences(url.replace('-',' ').replace('_',' '),aliases)
    near_negative=_v64_negative_near_target(title+' '+content,aliases)
    first_pos=_v65_first_alias_position(content,aliases)
    score=0; reasons=[]
    if title_count:
        score+=8; reasons.append('target in title')
    if url_count:
        score+=6; reasons.append('target in URL')
    if content_count>=3:
        score+=4; reasons.append('target prominent in source summary')
    elif content_count==2:
        score+=2
    elif content_count==1:
        score+=1
    if near_negative:
        score+=2; reasons.append('controversy linked near target')
    direct=bool(title_count or url_count)
    body_only=bool(content_count>=3 and first_pos<=280 and near_negative)
    matched=(direct and score>=6) or (body_only and score>=6)
    if not matched and not direct and content_count:
        return {'matched':False,'score':score,'label':'Rejected - incidental/body-only mention','reason':'The target is absent from the title and URL and is not sufficiently prominent in the source summary.'}
    label=('Direct - '+', '.join(reasons[:2])) if matched else 'Rejected - insufficient entity evidence'
    return {'matched':matched,'score':score,'label':label,'reason':'; '.join(reasons)}


def source_mentions_company(result,company_name,reviewed_pages=None):
    return entity_match_details(result,company_name,reviewed_pages).get('matched',False)


def _v65_discover_related_official_sites(company_name,primary_url,limit=2):
    """Conservatively discover an additional official sustainability/group site.

    This is generic and is used only when primary coverage is limited. Search results
    from regulators, media, NGOs, directories and social networks are excluded. A
    different-domain candidate must prominently identify the company and contain an
    official/corporate/sustainability relationship signal.
    """
    if not company_name or not external_search_configured():
        return []
    queries=[f'"{company_name}" official sustainability site',f'"{company_name}" corporate annual sustainability report']
    results,_,_,_=_v60_run_queries(queries)
    primary_root=_root_domain((urlparse(primary_url).hostname or ''))
    aliases=_v65_brand_aliases(company_name,[primary_url])
    candidates=[]; seen=set()
    for r in results:
        url=r.get('url','') or ''
        host=(urlparse(url).hostname or '').lower()
        root=_root_domain(host)
        if not root or root==primary_root or root in seen:
            continue
        if any(root==d or root.endswith('.'+d) for d in NON_OFFICIAL_SITE_DOMAINS):
            continue
        if _v60_source_kind(r)!='Other public source':
            continue
        title_content=_v64_norm((r.get('title','') or '')+' '+(r.get('content','') or ''))
        title_count,_=_v64_alias_occurrences(r.get('title','') or '',aliases)
        content_count,_=_v64_alias_occurrences(r.get('content','') or '',aliases)
        relation=any(term in title_content for term in V65_RELATED_TERMS)
        if not relation or not (title_count or content_count>=2):
            continue
        score=title_count*30+min(20,content_count*5)+(20 if 'official' in title_content else 0)+(15 if relation else 0)
        if score<45:
            continue
        candidates.append((score,f'https://{host}')); seen.add(root)
    candidates.sort(reverse=True)
    return [url for _,url in candidates[:limit]]


def crawl_with_related_sites(original_url,overall_deadline=None,company_name_hint=''):
    """Generic multi-domain official crawl with a protected primary-site budget."""
    if overall_deadline is None:
        overall_deadline=time.time()+CRAWL_BUDGET_SECONDS
    crawl_log=[]; source_notes=[]; all_text=[]; all_pages=[]; primary_error=None
    host=(urlparse(original_url).hostname or '').lower()
    hint=company_name_hint or _v65_scan_input_company_hint('',original_url)
    known=[]
    for brand,domains in KNOWN_GROUP_DOMAINS.items():
        if brand in host:
            known.extend(domains)
    reserve=8 if known else 0
    primary_deadline=max(time.time()+6,overall_deadline-reserve) if reserve else overall_deadline
    try:
        txt,pages=crawl(original_url,max_extra_pages=CRAWL_TARGET_EXTRA_PAGES,deadline=primary_deadline,log=crawl_log)
        if txt.strip():
            all_text.append(txt); all_pages.extend(pages)
    except Exception as exc:
        primary_error=exc
    candidates=list(dict.fromkeys(known))
    limited=(len(all_pages)<4 or sum(len(x) for x in all_text)<3500)
    if limited and time.time()<overall_deadline-5:
        for c in _v65_discover_related_official_sites(hint,original_url,limit=2):
            if c not in candidates:
                candidates.append(c)
    if len(all_pages)<3:
        for c in related_company_sites(original_url,max_sites=1):
            if c not in candidates:
                candidates.append(c)
    for candidate in candidates:
        if time.time()>=overall_deadline-2:
            break
        try:
            remaining_slots=max(2,min(4,CRAWL_TARGET_EXTRA_PAGES-max(0,len(all_pages)-1)))
            rt,rpages=crawl(candidate,max_extra_pages=remaining_slots,deadline=overall_deadline,log=crawl_log,candidate_source='related_domain')
            if len(rt)>300:
                all_text.append('\n\nRELATED OFFICIAL COMPANY SITE: '+candidate+'\n'+rt)
                all_pages.extend([p for p in rpages if p not in all_pages])
                source_notes.append(f'Official related company site also checked: {candidate}')
        except Exception:
            pass
    if not all_text:
        raise primary_error if primary_error is not None else ValueError(f'Could not access {original_url}.')
    return '\n\n'.join(all_text)[:180000],all_pages[:16],source_notes,crawl_log



# -----------------------------
# V69 strict negative external-source gate
# -----------------------------
# External public-source signals must be adverse context, not merely articles that contain
# sustainability or labour vocabulary. The gate below is generic: it requires an explicit
# adverse event/criticism linked to the target and rejects promotional, achievement and
# exoneration headlines unless a strong regulator/legal event is also clearly stated.
_V69_POSITIVE_HEADLINE_TERMS=(
    'achieves','achieved','achievement','launches','launched','unveils','announces','signs mou',
    'partnership','partners with','collaboration','wins award','awarded','recognised','recognized',
    'certified','certification achieved','reports progress','milestone','cuts emissions',
    'reduces emissions','reaches target','opens new','invests in','initiative to','commits to',
    'pledges to','success story','named leader','tops ranking','improves sustainability'
)
_V69_EXONERATION_TERMS=(
    'cleared of','acquitted','complaint dismissed','case dismissed','no evidence of',
    'found no evidence','not misleading','claims were compliant','investigation closed without action',
    'charges dropped','allegations rejected','allegations unfounded'
)
_V69_GENERIC_ADVERSE=(
    'accused','alleged','alleges','alleging','allegation','criticised','criticized','criticism','backlash','controversy',
    'complaint','lawsuit','sued','court','investigation','investigating','probe','inquiry','watchdog',
    'regulator','authority','fine','fined','penalty','sanction','settlement','ruling','decision',
    'ban','banned','prohibited','breach','violation','misconduct','boycott','protest','strike'
)
_V69_GREEN_ADVERSE=(
    'greenwashing','misleading environmental','misleading green','deceptive environmental',
    'unsubstantiated environmental','false environmental','environmental claims complaint',
    'environmental claims investigation','misleading sustainability claims','advertising ban'
)
_V69_GREEN_ANCHORS_STRICT=(
    'greenwashing','environmental claim','environmental claims','sustainability claim',
    'sustainability claims','green claim','green claims','climate claim','carbon claim','carbon neutral','climate neutral',
    'net zero','emissions claim','recyclable','recycled content','eco claim','green claim',
    # Broadened to plain topical words, not just narrow multi-word claim phrases -- a report
    # can be squarely about greenwashing (e.g. "overstates the sustainability of its
    # collection while relying on fossil-fuel-based fabrics") without ever using one of the
    # phrases above, and this anchor check runs before any other acceptance path, so a
    # too-narrow list here silently drops the whole result regardless of how explicit the
    # rest of the text is.
    'environmental','environment','sustainability','sustainable','climate','carbon','emission','emissions',
    'recyclable','recycled','recycling','circular','ecological','eco-friendly','fossil fuel','fossil-fuel'
)
_V69_SOCIAL_ADVERSE=(
    'forced labour','forced labor','child labour','child labor','modern slavery','wage theft',
    'illegal working hours','excessive working hours','unsafe working conditions','worker exploitation',
    'labour exploitation','labor exploitation','union busting','human rights abuse',
    'labour rights violation','labor rights violation','excessive overtime','low wages','poverty wages','discrimination','harassment','underpaid workers',
    'poverty wages','low wages','unpaid wages','workplace deaths','factory deaths'
)
_V69_SOCIAL_ANCHORS_STRICT=(
    'worker','workers','employee','employees','labour','labor','wage','wages','working hours',
    'factory','factories','supplier','supply chain','human rights','union','workplace','forced labour',
    'forced labor','child labour','child labor','modern slavery','discrimination','harassment'
)
_V69_STRONG_ACTION_PATTERNS=(
    r'\b(fined|penalised|penalized|sanctioned|banned|prohibited|convicted|found liable)\b',
    r'\b(regulator|authority|watchdog|court|prosecutor)\b.{0,80}\b(investigat|accus|fine|penalt|sanction|rule|complaint)',
    r'\b(lawsuit|legal action|formal complaint|criminal investigation|regulatory investigation)\b',
    r'\b(found|documented|reported)\b.{0,80}\b(forced labour|forced labor|child labour|child labor|illegal working hours|wage theft|unsafe working conditions)\b',
)


def _v69_term_hits(text,terms):
    return [term for term in terms if _v62_term_present(text,term)]


def _v69_strong_action(text):
    return any(re.search(pattern,text or '',flags=re.I|re.S) for pattern in _V69_STRONG_ACTION_PATTERNS)




def is_negative_external_source(result):
    accepted,reason=_v69_external_polarity(result,'social')
    if isinstance(result,dict) and accepted: result['_negative_reason']=reason
    return accepted


def is_green_negative_source(result):
    accepted,reason=_v69_external_polarity(result,'green')
    if isinstance(result,dict) and accepted: result['_negative_reason']=reason
    return accepted


# -----------------------------
# V71 EXTERNAL-SIGNAL DISCOVERY + RECALL/PRECISION BALANCE
# -----------------------------
# V69/V70 correctly blocked positive and company-owned sources, but the discovery layer
# could still return no visible signal for a company with well-documented regulator, NGO
# or investigative-media coverage. V71 keeps the strict final gate and improves recall by
# combining (1) focused news searches and (2) source-constrained regulator/stakeholder
# searches. The logic is company-agnostic; no result is preloaded for a specific company.

_V71_REGULATOR_DOMAINS=(
    'commission.europa.eu','ec.europa.eu','digital-strategy.ec.europa.eu',
    'competition-policy.ec.europa.eu','agcm.it','autoritedelaconcurrence.fr',
    'economie.gouv.fr','asa.org.uk','cma.gov.uk','acm.nl','ftc.gov','justice.gov',
    'gov.uk','parliament.uk','oecd.org','ilo.org','ohchr.org'
)
_V71_GREEN_STAKEHOLDER_DOMAINS=(
    'reuters.com','theguardian.com','bbc.com','bbc.co.uk','esgdive.com','esgtoday.com',
    'business-humanrights.org','changingmarkets.org','greenpeace.org','clientearth.org',
    'publiceye.ch','thefashionlaw.com','businessoffashion.com'
)
_V71_SOCIAL_STAKEHOLDER_DOMAINS=(
    'business-humanrights.org','publiceye.ch','chinalaborwatch.org','antislavery.org',
    'cleanclothes.org','labourbehindthelabel.org','hrw.org','humanrightswatch.org',
    'amnesty.org','reuters.com','theguardian.com','bbc.com','bbc.co.uk','esgdive.com',
    'supplychaindive.com','industriall-union.org'
)
_V71_COMPANY_DOCUMENT_MARKERS=(
    'modern slavery statement','modern slavery act transparency statement',
    'transparency statement','annual report','sustainability report','esg report',
    'human rights policy','human-rights policy','supplier code','supplier code of conduct',
    'code of conduct','responsible sourcing policy','responsible-sourcing policy',
    # v91.2: a Global Framework Agreement (a joint company/global-union-federation text --
    # e.g. Umicore's own French-language "Convention de développement durable" with
    # IndustriALL, hosted on the UNION's domain, not Umicore's) is the company stating its
    # own policy commitments, not an independent adverse finding -- yet every marker above
    # was English-only, so this whole document class (and any French/Dutch-language company
    # policy document, common for Belgian/French companies this tool targets) fell straight
    # through to the adverse-vocabulary check below, which then flagged ordinary policy
    # language ("interdiction du travail forcé" = "prohibition of forced labour") as a
    # negative external signal. Live-reproduced against the exact Umicore/IndustriALL PDF.
    'global framework agreement','framework agreement','collective bargaining agreement',
    'collective agreement','joint declaration','social charter','code of ethics',
    # French
    'déclaration de transparence','rapport annuel','rapport de durabilité',
    'rapport de développement durable','politique des droits humains',
    "politique droits de l'homme",'code de conduite fournisseur',
    'code de conduite des fournisseurs','code de conduite',
    "politique d'approvisionnement responsable",'convention de développement durable',
    'accord-cadre mondial','accord cadre mondial','accord cadre','accord collectif',
    # Dutch
    'transparantieverklaring','jaarverslag','duurzaamheidsverslag','mensenrechtenbeleid',
    'gedragscode leveranciers','leveranciersgedragscode','gedragscode',
    'beleid verantwoorde inkoop','raamovereenkomst','collectieve overeenkomst'
)
_V71_DOCUMENT_OVERRIDE_TITLE_TERMS=(
    'fined','fine over','investigation','investigates','regulator','authority finds',
    'complaint','lawsuit','court','criticises','criticizes','accuses','alleges','allegations',
    'report finds','report reveals','found misleading','misleading statement','deceptive statement',
    # v91.2: added alongside the French/Dutch _V71_COMPANY_DOCUMENT_MARKERS above -- without
    # these, a genuinely adverse French/Dutch-titled article (e.g. a regulator investigation)
    # whose body happened to also mention a policy-document phrase like "rapport annuel" would
    # now be wrongly suppressed as a company document, the opposite failure to the one being
    # fixed.
    'amende','enquête','enquêtes','régulateur','autorité','plainte','poursuite','tribunal',
    'critique','critiques','accuse','accusé','accusée','allégations','trompeur','trompeuse',
    'boete','onderzoek','toezichthouder','klacht','rechtszaak','rechtbank','bekritiseert',
    'beschuldigt','beschuldigingen','misleidend','misleidende'
)
_V71_ADVERSE_EVENT_TERMS=(
    'accused','accuses','alleged','alleges','alleging','allegation','allegations',
    'criticised','criticized','criticism','concern','concerns','controversy','complaint',
    'investigation','investigating','probe','inquiry','fine','fined','penalty','sanction',
    'lawsuit','sued','court','ruling','breach','breaches','violation','violations',
    'exposed','exposes','reveals','revealed','report finds','report found','found',
    'fails','failed','failure','refutes','contradicts','contradicted','illegal','risk','risks',
    # NGO/investigative reporting on greenwashing and social washing very often criticises a
    # company in plain descriptive language ("overstates", "downplays", "exaggerates") rather
    # than using an explicit legal/regulatory word -- without these, a substantive critical
    # report could fail every acceptance path below and be silently dropped.
    'overstate','overstates','overstated','overstating','overclaim','overclaims','overclaimed',
    'exaggerate','exaggerates','exaggerated','exaggerating','downplay','downplays','downplayed',
    'inflated claim','inflated claims','unsubstantiated',
    'misleidend','misleidende','onderzoek','boete','overtreding','beschuldigd',
    'trompeur','trompeuse','enquête','amende','violation','accusé'
)
_V71_GREEN_EXPLICIT=(
    'greenwashing','misleading environmental claim','misleading environmental claims',
    'misleading sustainability claim','misleading sustainability claims',
    'deceptive environmental claim','deceptive environmental claims',
    'false environmental claim','false environmental claims','environmental claims complaint',
    'environmental claims investigation','misleidende milieuclaim','misleidende milieuclaims',
    'misleidende duurzaamheidsclaim','misleidende duurzaamheidsclaims','ecoblanchiment',
    'écoblanchiment','allégation environnementale trompeuse','allégations environnementales trompeuses'
)
_V71_SOCIAL_EXPLICIT=(
    'forced labour','forced labor','child labour','child labor','modern slavery','wage theft',
    'illegal working hours','excessive working hours','long working hours','75-hour week',
    '75-hour weeks','poor working conditions','unsafe working conditions','low wages',
    'worker exploitation','workers exploitation','labour exploitation','labor exploitation',
    'labour rights violation','labour rights violations','labor rights violation',
    'labor rights violations','human rights abuse','human rights abuses','union busting',
    'dwangarbeid','kinderarbeid','illegale werkuren','slechte arbeidsomstandigheden',
    'travail forcé','travail des enfants','conditions de travail illégales',
    'mauvaises conditions de travail','exploitation des travailleurs'
)


def _v71_company_document_without_adverse_finding(result):
    """Reject a company's own policy/report even when hosted on a public register."""
    title=re.sub(r'\s+',' ',str((result or {}).get('title','') or '')).lower()
    content=re.sub(r'\s+',' ',str((result or {}).get('content','') or '')).lower()[:900]
    url=str((result or {}).get('url','') or '').lower().replace('-',' ')
    text=' '.join((title,content,url))
    if not any(_v62_term_present(text,marker) for marker in _V71_COMPANY_DOCUMENT_MARKERS):
        return False
    # A company statement commonly discusses generic "risks", "concerns" or even
    # "violations"; those words do not turn it into an independent adverse source.
    # Override the document exclusion only when the title itself frames a concrete
    # third-party allegation, investigation, criticism or enforcement outcome.
    return not any(_v62_term_present(title,term) for term in _V71_DOCUMENT_OVERRIDE_TITLE_TERMS)


def _v69_external_polarity(result,dimension='social'):
    """V71 final polarity gate: negative-only, but no longer blind to clear adverse titles."""
    title=re.sub(r'\s+',' ',str((result or {}).get('title','') or '')).strip().lower()
    content=re.sub(r'\s+',' ',str((result or {}).get('content','') or '')).strip().lower()
    url=str((result or {}).get('url','') or '').lower()
    combined=' '.join((title,content,url))
    first_content=content[:900]
    if _v71_company_document_without_adverse_finding(result):
        return False,'Company-authored policy/report without an independent adverse finding'
    if any(_v62_term_present(title,term) for term in _V69_EXONERATION_TERMS):
        return False,'Exoneration or dismissal headline, not negative stakeholder news'
    positive_title=_v69_term_hits(title,_V69_POSITIVE_HEADLINE_TERMS)
    adverse_title=_v69_term_hits(title,_V71_ADVERSE_EVENT_TERMS)
    adverse_body=_v69_term_hits(first_content,_V71_ADVERSE_EVENT_TERMS)
    strong_action=_v69_strong_action(title+' '+first_content)
    recognised=_v60_source_kind(result)!='Other public source'
    if dimension=='green':
        explicit_title=_v69_term_hits(title,_V71_GREEN_EXPLICIT)
        explicit_body=_v69_term_hits(first_content,_V71_GREEN_EXPLICIT)
        anchors=_v69_term_hits(combined,_V69_GREEN_ANCHORS_STRICT+('milieu','duurzaamheid','environnement','durabilité'))
    else:
        explicit_title=_v69_term_hits(title,_V71_SOCIAL_EXPLICIT)
        explicit_body=_v69_term_hits(first_content,_V71_SOCIAL_EXPLICIT)
        anchors=_v69_term_hits(combined,_V69_SOCIAL_ANCHORS_STRICT+('arbeid','werknemer','werknemers','travail','travailleurs','salaires'))
    if not anchors and not explicit_title and not explicit_body:
        return False,'No relevant environmental or social controversy anchor'
    if positive_title and not (explicit_title or adverse_title or strong_action):
        return False,'Positive/promotional headline without an explicit adverse event'
    if dimension=='green':
        # A recognised independent source (NGO, regulator, investigative press) describing a
        # concrete green-topic criticism in plain language ("overstates its sustainability")
        # is credible adverse evidence even with only one adverse marker -- requiring two, as
        # the last fallback below still does for unrecognised sources, was silently dropping
        # legitimate NGO/investigative reporting that never happens to repeat itself twice in
        # a short search snippet.
        accepted=bool(explicit_title) or strong_action or (bool(explicit_body) and (bool(adverse_title) or bool(adverse_body) or recognised)) or (bool(anchors) and recognised and bool(adverse_body)) or (bool(anchors) and len(set(adverse_body))>=2)
    else:
        accepted=strong_action or bool(adverse_title) or (bool(explicit_title) and recognised) or (bool(explicit_body) and (bool(adverse_body) or recognised)) or (bool(anchors) and recognised and len(set(adverse_body))>=2)
    if not accepted:
        return False,'No sufficiently explicit adverse event, allegation, criticism or finding'
    reasons=[]
    if explicit_title: reasons.append('explicit adverse issue in title')
    elif explicit_body: reasons.append('explicit adverse issue in opening summary')
    if adverse_title: reasons.append('adverse event/finding in title')
    if strong_action: reasons.append('formal enforcement/legal action')
    if recognised: reasons.append('recognised independent source type')
    return True,', '.join(dict.fromkeys(reasons)) or 'clear adverse external context'


# Serialising Tavily calls process-wide, in case the deployment's key/plan is sensitive to
# concurrent requests, plus one short retry after a brief pause on 429/432. This did NOT
# resolve repeated live 432s even though a single manual request via Tavily's own Playground
# succeeds on the same key -- so concurrency is not (or not the only) cause. Python's HTTPError
# only exposes the status line by default; the code below now reads and surfaces Tavily's own
# JSON error body (e.g. a specific "invalid parameter"/plan-restriction message) instead of the
# bare "HTTP Error 432: " we were logging before, so the real reason is visible in the report's
# provider_attempts instead of having to keep guessing.
_TAVILY_RATE_LOCK=threading.Semaphore(1)

# v90: a scan issues up to ~7 external-search queries per dimension (green + social,
# each with a primary batch plus a same-dimension fallback when too few results come
# back), and every query calls all 3 configured providers. When a provider's account is
# genuinely out of quota/credits (confirmed live for Tavily, Serper and Google Custom
# Search on 2026-08-31 -- see the v89 error-diagnostics fix), EVERY one of those ~14
# query x provider calls still pays that provider's full request+retry latency (Tavily
# alone retries once after a 2s sleep on 429) before failing, because each call had no
# memory of the identical failure moments earlier. Live-reproduced: a single "AB InBev"
# scan took 250 SECONDS end-to-end for exactly this reason, even after the separate
# domain-resolution hang above was fixed. A short process-wide cooldown means the first
# failure for a provider in this run is enough -- every subsequent call to that provider
# (this query's siblings, the fallback round, and the other dimension) skips it
# near-instantly instead of re-paying the same doomed request.
# v91.1: cooling down only on a keyword match against the error text ('quota', 'credit',
# etc.) missed a real, live failure mode -- a live "AB InBev" run showed Google Custom
# Search fail with "This project does not have the access to Custom Search JSON API",
# a permanent per-project configuration error with none of those keywords, so it kept
# being retried on every later query instead of entering cooldown. Any failure from a
# configured provider within the same short scan is unlikely to recover a few seconds
# later regardless of its wording, so cool down on ANY exception, not just ones that
# happen to mention quota/credits.
_PROVIDER_COOLDOWN_LOCK=threading.Lock()
_PROVIDER_COOLDOWN_UNTIL={}
_PROVIDER_COOLDOWN_SECONDS=90

def _v90_provider_in_cooldown(provider):
    with _PROVIDER_COOLDOWN_LOCK:
        return time.time()<_PROVIDER_COOLDOWN_UNTIL.get(provider,0)

def _v90_note_provider_result(provider):
    with _PROVIDER_COOLDOWN_LOCK:
        _PROVIDER_COOLDOWN_UNTIL[provider]=time.time()+_PROVIDER_COOLDOWN_SECONDS

def tavily_search(q,max_results=5,topic='general',include_domains=None,exclude_domains=None,search_depth='basic'):
    """Tavily search with optional news/source controls for the external-signal layer."""
    if not TAVILY_API_KEY:
        return []
    payload={'query':q,'search_depth':search_depth,'max_results':max_results,
             'include_answer':False,'include_raw_content':False,'topic':topic}
    if include_domains:
        payload['include_domains']=list(dict.fromkeys(include_domains))[:300]
    if exclude_domains:
        payload['exclude_domains']=list(dict.fromkeys(exclude_domains))[:150]
    req=Request('https://api.tavily.com/search',data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+TAVILY_API_KEY},method='POST')
    with _TAVILY_RATE_LOCK:
        for attempt in range(2):
            try:
                with urlopen(req,timeout=10) as r:
                    data=json.loads(r.read().decode('utf-8',errors='ignore'))
                break
            except HTTPError as e:
                try: body=e.read().decode('utf-8',errors='ignore')[:300].strip()
                except Exception: body=''
                if e.code in (429,432) and attempt==0:
                    time.sleep(2.0)
                    continue
                raise ValueError(f'HTTP Error {e.code}: {body or e.reason or "(no error body)"}') from e
    return [{'title':i.get('title',''),'url':i.get('url',''),'content':i.get('content',''),
             'score':i.get('score',0),'published_date':i.get('published_date','')} for i in data.get('results',[])]


def serper_search(q,max_results=5,include_domains=None,exclude_domains=None):
    """Serper.dev Google-SERP wrapper -- cheap fallback/alternative to Tavily."""
    if not SERPER_API_KEY:
        return []
    query=_v71_google_query(q,include_domains,exclude_domains)
    req=Request('https://google.serper.dev/search',
                data=json.dumps({'q':query,'num':max(1,min(max_results,20))}).encode(),
                headers={'X-API-KEY':SERPER_API_KEY,'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(req,timeout=10) as r:
            data=json.loads(r.read().decode('utf-8',errors='ignore'))
    except HTTPError as e:
        # v89: urlopen's HTTPError only exposes the bare status line by default ("HTTP Error
        # 400: Bad Request") -- the same class of gap already fixed for Tavily's own retry
        # logic, but never applied here. Serper's actual JSON error body (e.g. "not enough
        # credits", an invalid API key message, or a genuinely malformed query) is what
        # actually explains a 400/403, and was being silently discarded before it ever reached
        # provider_attempts in the scan diagnostics.
        try: body=e.read().decode('utf-8',errors='ignore')[:300].strip()
        except Exception: body=''
        raise ValueError(f'HTTP Error {e.code}: {body or e.reason or "(no error body)"}') from e
    out=[]
    for i in data.get('organic',[]):
        out.append({'title':i.get('title',''),'url':i.get('link',''),'content':i.get('snippet',''),
                     'score':1.0/max(1,i.get('position',1)),'published_date':i.get('date','')})
    return out


def _v71_google_query(query,include_domains=None,exclude_domains=None):
    value=query
    if include_domains:
        selected=list(dict.fromkeys(include_domains))[:8]
        value+=' ('+' OR '.join('site:'+d for d in selected)+')'
    for domain in list(dict.fromkeys(exclude_domains or []))[:5]:
        value+=' -site:'+domain
    return value


def search_public_sources(query,max_results=8,topic='general',include_domains=None,exclude_domains=None,search_depth='basic'):
    """Combine configured providers while preserving source and company-domain controls."""
    attempts=[]; gathered=[]
    def _run(provider):
        if provider=='Serper':
            if not SERPER_API_KEY:
                return [],{'provider':provider,'status':'not_configured'}
            if _v90_provider_in_cooldown(provider):
                return [],{'provider':provider,'status':'skipped_cooldown'}
            try:
                res=serper_search(query,max_results,include_domains=include_domains,exclude_domains=exclude_domains)
                for item in res: item['provider']=provider
                return res,{'provider':provider,'status':'ok','results':len(res)}
            except Exception as exc:
                _v90_note_provider_result(provider)
                return [],{'provider':provider,'status':'failed','error':str(exc)[:180]}
        if provider=='Tavily':
            if not TAVILY_API_KEY:
                return [],{'provider':provider,'status':'not_configured'}
            if _v90_provider_in_cooldown(provider):
                return [],{'provider':provider,'status':'skipped_cooldown'}
            try:
                res=tavily_search(query,max_results,topic=topic,include_domains=include_domains,exclude_domains=exclude_domains,search_depth=search_depth)
                for item in res: item['provider']=provider
                return res,{'provider':provider,'status':'ok','results':len(res)}
            except Exception as exc:
                _v90_note_provider_result(provider)
                return [],{'provider':provider,'status':'failed','error':str(exc)[:180]}
        if not (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX):
            return [],{'provider':provider,'status':'not_configured'}
        if _v90_provider_in_cooldown(provider):
            return [],{'provider':provider,'status':'skipped_cooldown'}
        try:
            res=google_search(_v71_google_query(query,include_domains,exclude_domains),max_results)
            for item in res: item['provider']=provider
            return res,{'provider':provider,'status':'ok','results':len(res)}
        except Exception as exc:
            _v90_note_provider_result(provider)
            return [],{'provider':provider,'status':'failed','error':str(exc)[:180]}
    providers=['Serper','Tavily','Google Custom Search']
    if EXTERNAL_SEARCH_ALL_PROVIDERS:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(_run,provider) for provider in providers]
            for future in as_completed(futures):
                results,attempt=future.result(); gathered.extend(results); attempts.append(attempt)
    else:
        for provider in providers:
            results,attempt=_run(provider); gathered.extend(results); attempts.append(attempt)
            if results: break
    unique=[]; seen=set()
    for item in gathered:
        key=_v60_canonical_url(item.get('url',''))
        if key and key not in seen:
            unique.append(item); seen.add(key)
    unique.sort(key=lambda item:float(item.get('score',0) or 0),reverse=True)
    return unique[:max_results*2],attempts


def _v71_query_specs(company_name,dimension):
    names=_v63_company_query_names(company_name)
    brand=names[0]
    q='"'+brand.replace('"','')+'"'
    # v79: independent/organic press coverage very rarely spells out a company's full
    # registered or marketing name ("Protix Ingredients") -- it just says "Protix". A
    # quoted exact-phrase search on the long form systematically misses that coverage. Use
    # the shorter brand form (already computed by _v63_company_query_names, which puts the
    # single-token brand second precisely because it has better recall) for the
    # topically-narrow complaint/investigation/NL/FR queries, where "complaint",
    # "investigation" etc. keep the query specific enough that a short, less unique brand
    # name is still a safe bet -- entity_match_details() independently verifies afterwards
    # that any retained result is actually about this company, so a short name cannot smuggle
    # an unrelated result past the pipeline. The plain "news"-topic queries keep the long
    # form, since those have no other disambiguating keyword to lean on.
    short=names[1] if len(names)>1 and names[1].lower()!=brand.lower() else brand
    qs='"'+short.replace('"','')+'"'
    if dimension=='green':
        stakeholder=_V71_REGULATOR_DOMAINS+_V71_GREEN_STAKEHOLDER_DOMAINS
        return [
            {'query':f'{q} greenwashing misleading environmental claims fine regulator','topic':'news'},
            {'query':f'{qs} sustainability claims investigation complaint ruling','topic':'news'},
            {'query':f'{q} environmental sustainability claims enforcement','topic':'general','include_domains':stakeholder},
            # v78: a single query mixing English/French/Dutch terms in one string performs
            # poorly for surfacing genuinely Dutch- or French-language coverage -- a real
            # negative article (found live, missed entirely: "Klacht tegen insectenfabriek
            # Protix wegens misleidende duurzaamheidsclaims") never appeared in the 23 raw
            # results returned for the old mixed query, even though it passes every
            # downstream entity/polarity check when tested directly. Split into two clean,
            # mono-lingual queries instead of one multilingual jumble.
            # v80: deeper still -- these two were *also* restricted to `stakeholder`, a
            # hardcoded allowlist of ~13 major English-language outlets (Reuters, Guardian,
            # BBC, Greenpeace...) with zero Belgian/Dutch/French domains on it. Tavily's and
            # Serper's include_domains is a hard filter, not a preference, so a Dutch or
            # French-language query combined with that allowlist could *never* return a
            # Dutch or French result -- the two restrictions directly contradicted each
            # other. Dropped include_domains here so these queries can actually reach
            # local-language independent press; the query text's own specificity plus
            # entity_match_details()/is_green_negative_source() downstream still gate what
            # gets retained.
            # v81: Tavily's 'basic' search_depth is a lighter, cheaper retrieval pass that can
            # miss smaller/less-prominent pages; 'advanced' does deeper retrieval at higher
            # API cost, which is a reasonable trade specifically for the two local-language
            # queries above -- they are the ones most likely to be searching a smaller,
            # non-mainstream domain in the first place. Not applied to the English queries,
            # which already lean on major outlets where 'basic' performs well.
            # v82: named the actual Dutch/French national advertising-standards regulators
            # (Reclame Code Commissie, ARPP) explicitly, the same way the English queries
            # already say "regulator" -- a real, live complaint found during this
            # investigation ("Wakker Dier dient een klacht in bij de Reclame Code Commissie
            # tegen Protix") uses this exact institution name, and any future NL/FR
            # greenwashing complaint is likewise likely to be filed with it.
            {'query':f'{qs} misleidende duurzaamheidsclaim klacht Reclame Code Commissie greenwashing','topic':'general','search_depth':'advanced'},
            {'query':f'{qs} allégation environnementale trompeuse plainte ARPP','topic':'general','search_depth':'advanced'},
        ]
    stakeholder=_V71_REGULATOR_DOMAINS+_V71_SOCIAL_STAKEHOLDER_DOMAINS
    return [
        {'query':f'{q} forced labour child labour workers allegations investigation','topic':'news'},
        {'query':f'{qs} working conditions wages overtime labour rights report','topic':'news'},
        {'query':f'{q} workers suppliers forced labour human rights','topic':'general','include_domains':stakeholder},
        # v78/v80: split mixed-language query into Dutch and French, and (see the matching
        # v80 note on the green queries above) dropped the English-outlet-only
        # include_domains restriction that made a Dutch/French result structurally
        # impossible to return in the first place.
        # v81: 'advanced' search_depth for these two -- see the matching note on the green
        # queries above.
        {'query':f'{qs} dwangarbeid misstanden arbeidsomstandigheden klacht','topic':'general','search_depth':'advanced'},
        {'query':f'{qs} travail forcé plainte conditions de travail','topic':'general','search_depth':'advanced'},
    ]


def _v71_run_query_specs(specs,reviewed_pages=None):
    official=sorted(_v65_owned_roots(reviewed_pages))
    all_results=[]; attempts=[]; providers=set(); seen=set(); run_queries=[]
    specs=list(specs)[:EXTERNAL_SIGNAL_MAX_QUERIES]
    def _one(spec):
        query=spec['query']
        return spec,search_public_sources(query,EXTERNAL_SIGNAL_RESULTS_PER_QUERY,
            topic=spec.get('topic','general'),include_domains=spec.get('include_domains'),exclude_domains=official,
            search_depth=spec.get('search_depth','basic'))
    with ThreadPoolExecutor(max_workers=min(EXTERNAL_SIGNAL_WORKERS,len(specs) or 1)) as pool:
        futures=[pool.submit(_one,spec) for spec in specs]
        for future in as_completed(futures):
            spec,(results,provider_attempts)=future.result(); query=spec['query']; run_queries.append(query)
            attempts.extend([dict(attempt,query=query,topic=spec.get('topic','general')) for attempt in provider_attempts])
            for item in results:
                key=_v60_canonical_url(item.get('url',''))
                if key and key not in seen:
                    row=dict(item); row['query']=query; row['credibility']=source_credibility(row)
                    all_results.append(row); seen.add(key)
                    if row.get('provider'): providers.add(row['provider'])
    return all_results,attempts,providers,run_queries


def _v64_search_dimension(company_name,findings,dimension,reviewed_pages=None):
    specs=_v71_query_specs(company_name,dimension)
    all_results,attempts,providers,run_queries=_v71_run_query_specs(specs,reviewed_pages)
    ranked=_v60_rank_dedupe(all_results,company_name,dimension,30,reviewed_pages)
    fallback_used=False
    if len(ranked)<2:
        fallback_used=True
        brand='"'+_v63_company_query_names(company_name)[0].replace('"','')+'"'
        pool=(_V71_REGULATOR_DOMAINS+(_V71_GREEN_STAKEHOLDER_DOMAINS if dimension=='green' else _V71_SOCIAL_STAKEHOLDER_DOMAINS))
        fallback_query=(f'{brand} climate carbon recyclable circular claims criticism' if dimension=='green'
                        else f'{brand} factories suppliers low wages excessive working hours exploitation')
        more,more_attempts,more_providers,more_queries=_v71_run_query_specs(
            [{'query':fallback_query,'topic':'general','include_domains':pool}],reviewed_pages)
        attempts.extend(more_attempts); providers.update(more_providers); run_queries.extend(more_queries)
        seen={_v60_canonical_url(item.get('url','')) for item in all_results}
        for item in more:
            key=_v60_canonical_url(item.get('url',''))
            if key and key not in seen:
                all_results.append(item); seen.add(key)
        ranked=_v60_rank_dedupe(all_results,company_name,dimension,30,reviewed_pages)
    matched=[item for item in all_results if entity_match_details(item,company_name,reviewed_pages)['matched']]
    negative=[item for item in matched if (is_green_negative_source(item) if dimension=='green' else is_negative_external_source(item))]
    diagnostics={'raw_result_count':len(all_results),'company_matched_count':len(matched),
        'negative_candidate_count':len(negative),'retained_count':len(ranked),'fallback_used':fallback_used,
        'company_owned_rejected_count':sum(1 for item in all_results if is_company_owned_source(item,company_name,reviewed_pages)),
        'providers_used':sorted(providers),'queries_run':list(dict.fromkeys(run_queries))}
    return ranked,all_results,attempts,providers,run_queries,diagnostics


def _v60_rank_dedupe(results,company_name,dimension='social',limit=20,reviewed_pages=None):
    """V69 ranker: only explicitly negative sources can enter the retained result set."""
    negative_fn=is_green_negative_source if dimension=='green' else is_negative_external_source
    candidates=[]; seen=set()
    for r in results or []:
        match=entity_match_details(r,company_name,reviewed_pages)
        if not match['matched']:
            continue
        if is_company_owned_source(r,company_name,reviewed_pages):
            continue
        if not negative_fn(r):
            continue
        key=_v60_canonical_url(r.get('url',''))
        if not key or key in seen:
            continue
        score=_v60_signal_score(r,company_name,dimension)
        if score<0:
            continue
        item=dict(r); item['_signal_score']=score+match['score']; item['source_kind']=_v60_source_kind(item)
        item['entity_match']=match['label']; item['entity_match_reason']=match['reason']
        item['_negative_reason']=r.get('_negative_reason','Explicit adverse event or criticism')
        candidates.append(item); seen.add(key)
    candidates.sort(key=lambda x:(x.get('_signal_score',0),x.get('published_date','')),reverse=True)
    return _dedupe_similar_sources(candidates)[:limit]

def main():
    print(f"Sustainability Claims Risk Scan {APP_VERSION}"); print(f"Serving on http://{HOST}:{PORT}"); print("Tavily configured:",bool(TAVILY_API_KEY)); print("Serper configured:",bool(SERPER_API_KEY)); print("Google Search configured:",bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)); print("External search configured:",external_search_configured()); ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()
