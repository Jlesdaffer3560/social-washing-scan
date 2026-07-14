#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime, base64, zipfile, re, io, time

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

APP_VERSION="hostable_v57q_external_source_status_severity_dedup"
# v56: standard browser User-Agent instead of a self-identifying scanner UA. A UA string
# that announces itself as an assessment/scanner tool is the easiest possible fingerprint
# for corporate bot-protection (Akamai/PerimeterX/Cloudflare-style WAFs) to block on,
# independent of any other fingerprinting. This does not defeat sophisticated bot
# detection, but removes the most trivial and unnecessary self-inflicted cause of it.
CRAWLER_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
 ("High",["fast fashion","apparel","textile","garment","fashion","clothing","discount","supermarket","grocery","food retail","catering","facilities","outsourced","platform","delivery","commodity","cocoa","palm oil","coffee","cotton"],"higher exposure to low-wage work, complex supply chains, migrant or seasonal labour, supplier pressure, audit limitations and worker-voice challenges"),
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
 {"name":"CSRD / ESRS S1-S4 (post-Omnibus I: >1,000 employees AND >EUR450M net turnover; reporting from FY2027)","use":"Connect social claims to policies, actions, targets and metrics across own workforce (S1), value-chain workers (S2), affected communities (S3) and consumers (S4). Post-Omnibus I: first CSRD report due 2028 for in-scope companies. Belgian transposition via Wet van 6 februari 2025."},
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
    if "aspirational" in x or "future social" in x: return ["EmpCo / Directive (EU) 2024/825 Art. 6(1)(b) & 6(2)(d) (by analogy: future-performance claims require a verifiable, time-bound implementation plan)","CSRD/ESRS S1-S2","OECD Guidelines","UNGPs","ILO","UNGC"]
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
        words=[w for w in re.findall(r'[a-z]{4,}', title) if w not in ('this','that','with','from','have','been','will','their','about')]
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

def compact_sources(results,limit=6):
    results=_dedupe_similar_sources(results)
    out=[]
    for r in results[:limit]:
        txt=(r.get("title","")+" "+r.get("url","")+" "+r.get("content","")).lower()
        cat="Public web"
        if any(v in txt for v in ["ngo","amnesty","oxfam","human rights watch","clean clothes"]): cat="NGO / civil society"
        elif any(v in txt for v in ["gov","europa","regulator","authority","commission","oecd","ncp"]): cat="Government / regulator"
        elif any(v in txt for v in ["lawsuit","court","legal","complaint"]): cat="Legal / complaint"
        elif any(v in txt for v in ["reuters","ft.com","bbc","guardian","press"]): cat="Press"
        out.append({"title":r.get("title","")[:150],"url":r.get("url",""),"content":r.get("content","")[:220],"category":cat,
                     "credibility":source_credibility(r),"provider":r.get("provider",""),
                     "published_date":r.get("published_date","") or "Not available from source",
                     "status":_source_status(txt),"severity":_source_severity(txt),
                     "related_articles_count":r.get("related_articles_count",1)})
    return out

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip=False; self.parts=[]; self.links=[]; self.skip_tags={"script","style","noscript","svg","canvas","form"}
    def handle_starttag(self,tag,attrs):
        tag_l=tag.lower()
        if tag_l in self.skip_tags: self.skip=True
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
        if tag.lower() in self.skip_tags: self.skip=False
    def handle_data(self,data):
        if not self.skip:
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

def resolve_company_website(name):
    """Best-effort resolution of a bare company name (e.g. 'Inditex') to an official
    website URL. Tries web search first (Tavily, then Google CSE, when configured) and
    filters out social/news/directory domains; falls back to a best-guess domain when
    no search is configured or nothing usable was found."""
    query=f'{name} official website'
    results=[]
    try: results=tavily_search(query,max_results=5) or []
    except Exception: results=[]
    if not results:
        try: results=google_search(query,max_results=5) or []
        except Exception: results=[]
    for r in results:
        host=(urlparse(r.get('url','')).hostname or '').lower()
        bare=host[4:] if host.startswith('www.') else host
        if not bare: continue
        if any(bare==d or bare.endswith('.'+d) for d in NON_OFFICIAL_SITE_DOMAINS): continue
        return f'https://{host}', f'Company name "{name}" was resolved to {host} via web search. Verify this is the correct entity before relying on the result.'
    guess=f'https://www.{slugify_company_name(name)}.com'
    return guess, f'Company name "{name}" could not be verified via web search (no search provider configured or no confident match); the scan used a best-guess domain ({guess}). Please verify this is the correct company website and re-run with the exact URL if not.'

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

def crawl_with_related_sites(original_url,overall_deadline=None):
    """Crawl the requested URL plus a small number of likely related company sites.
    The requested URL remains the primary source. Related domains are added only when reachable.
    A single shared wall-clock deadline caps the ENTIRE operation (not per sub-step) so the
    request reliably returns well within Render's gateway timeout.

    v56: also returns a per-page crawl_log (list of dicts: url, ok, chars, thin, error) so the
    caller can tell "no risky claims found because none exist" apart from "no risky claims
    found because the crawl barely reached any real content" -- these are not the same thing
    and were previously indistinguishable in the output.
    """
    if overall_deadline is None:
        overall_deadline=time.time()+18
    crawl_log=[]
    source_notes=[]
    all_text=[]; all_pages=[]
    primary_error=None
    try:
        txt,pages=crawl(original_url,deadline=overall_deadline,log=crawl_log)
        all_text.append(txt); all_pages.extend(pages)
    except Exception as e:
        # v57 fix: previously an outright failure here (e.g. a 403 on the primary domain)
        # propagated immediately and skipped related_group_sites() below entirely -- so the
        # Zara -> Inditex style fallback never actually ran in the exact case it exists for
        # (the primary brand domain being fully blocked). Now we still try known related/group
        # domains before giving up.
        primary_error=e
    if time.time() < overall_deadline-3:
        for candidate in related_group_sites(original_url):
            if time.time()>=overall_deadline-2: break
            try:
                rt,rpages=crawl(candidate,deadline=overall_deadline,log=crawl_log)
                if len(rt)>500:
                    all_text.append('\n\nRELATED COMPANY SITE: '+candidate+'\n'+rt)
                    all_pages.extend([p for p in rpages if p not in all_pages])
                    source_notes.append(f"Related company site also checked: {candidate}")
            except Exception:
                pass
    if not all_text:
        raise primary_error if primary_error is not None else ValueError(f'Could not access {original_url}.')
    return '\n\n'.join(all_text)[:150000], all_pages[:16], source_notes, crawl_log

def replace_tld_with_be(url):
    """If a .com domain cannot be reached, try the same host with .be."""
    parsed=urlparse(url)
    host=parsed.hostname or ""
    if not host.endswith(".com"):
        return None
    new_host=host[:-4]+".be"
    netloc=new_host
    if parsed.port:
        netloc += f":{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()
def is_private(host):
    if host in {"localhost","127.0.0.1","0.0.0.0"}: return True
    try:
        for r in socket.getaddrinfo(host,None):
            ip=ipaddress.ip_address(r[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return True
    except Exception: return False
    return False
def fetch_html(url,timeout=7):
    p=urlparse(url)
    if p.scheme not in ("http","https") or not p.hostname: raise ValueError("Invalid URL.")
    if is_private(p.hostname): raise ValueError("Private/local URLs are blocked.")
    req=Request(url,headers={"User-Agent":CRAWLER_USER_AGENT,"Accept":"text/html,application/xhtml+xml"})
    with urlopen(req,timeout=max(2,timeout),context=ssl.create_default_context()) as r:
        if "html" not in r.headers.get("content-type","").lower(): raise ValueError("URL does not return an HTML page.")
        return r.read(2000000).decode("utf-8",errors="ignore")

def fetch_page_content(url,timeout=7):
    """Like fetch_html, but also accepts PDFs (the format company annual/CSR/ESG/sustainability
    reports are almost always published in) and returns extracted plain text either way.
    v56: this is what lets the crawler pick up "the company's own reporting" -- e.g. a
    'Download our Sustainability Report' PDF link discovered on the company's own site --
    without depending on any external search API. Returns (text, content_kind)."""
    p=urlparse(url)
    if p.scheme not in ("http","https") or not p.hostname: raise ValueError("Invalid URL.")
    if is_private(p.hostname): raise ValueError("Private/local URLs are blocked.")
    req=Request(url,headers={"User-Agent":CRAWLER_USER_AGENT,"Accept":"text/html,application/xhtml+xml,application/pdf"})
    with urlopen(req,timeout=max(2,timeout),context=ssl.create_default_context()) as r:
        ctype=r.headers.get("content-type","").lower()
        if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
            data=r.read(4000000)
            return extract_pdf_text_best_effort(data), "pdf"
        if "html" not in ctype: raise ValueError("URL does not return an HTML or PDF document.")
        raw=r.read(2000000).decode("utf-8",errors="ignore")
        text,_=parse_html(raw)
        return text, "html"
def same_domain(u,base):
    h=urlparse(u).hostname or ""
    return h==base or h.endswith("."+base)
def relevant(h):
    h=h.lower()
    return any(k in h for k in ["sustain","responsib","people","human","rights","divers","inclusion","supplier","ethic","impact","community","accessibility","safety","annual","report","esg","environment","climate","circular","green","sourcing","governance","modern-slavery","modern_slavery","non-financial","investor"])
COMMON_PUBLIC_PATHS=['/sustainability','/sustainability-report','/csr','/esg','/responsibility',
    '/corporate-responsibility','/human-rights','/supply-chain','/policies','/investors',
    '/investor-relations','/about/sustainability','/about-us/sustainability','/en/sustainability',
    '/news','/press','/newsroom']

def discover_sitemap_urls(base_url, limit=40, deadline=None):
    """Best-effort sitemap discovery so the scan can reach pages that are not linked
    from the homepage. Silently returns [] on any failure (missing/blocked sitemap) or
    once the shared crawl deadline is reached."""
    host=urlparse(base_url).hostname or ''
    if not host: return []
    if deadline and time.time()>=deadline: return []
    scheme=urlparse(base_url).scheme or 'https'
    found=[]
    for path in ('/sitemap.xml',):
        if deadline and time.time()>=deadline: break
        try:
            t=min(5, max(2, deadline-time.time())) if deadline else 5
            req=Request(f'{scheme}://{host}{path}',headers={"User-Agent":CRAWLER_USER_AGENT})
            with urlopen(req,timeout=t,context=ssl.create_default_context()) as r:
                body=r.read(1000000).decode("utf-8",errors="ignore")
            locs=re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',body,flags=re.IGNORECASE)
            if '<sitemapindex' in body.lower() and locs and (not deadline or time.time()<deadline):
                try:
                    t2=min(4, max(2, deadline-time.time())) if deadline else 4
                    req2=Request(locs[0],headers={"User-Agent":CRAWLER_USER_AGENT})
                    with urlopen(req2,timeout=t2,context=ssl.create_default_context()) as r2:
                        body2=r2.read(1000000).decode("utf-8",errors="ignore")
                    locs=re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',body2,flags=re.IGNORECASE)
                except Exception: pass
            if locs: found=locs; break
        except Exception: continue
    out=[]; seen=set()
    for u in found:
        u=u.strip()
        if same_domain(u,host) and u not in seen:
            seen.add(u); out.append(u)
    return out[:limit]

THIN_CONTENT_CHARS=400  # v56: a 200-OK page with less extracted text than this is flagged
                         # "thin" -- most likely a JS-rendered shell or a soft-block/interstitial,
                         # not a genuinely near-empty page. Used for confidence, not scoring.

def _log_fetch_success(log,url,chars):
    if log is not None:
        log.append({"url":url,"ok":True,"http_status":200,"chars":chars,"thin":chars<THIN_CONTENT_CHARS,"error":None})

def _log_fetch_failure(log,url,err):
    if log is not None:
        code=err.code if isinstance(err,HTTPError) else None
        log.append({"url":url,"ok":False,"http_status":code,"chars":0,"thin":False,"error":_describe_fetch_error(err)})

def crawl(url,max_extra_pages=3,deadline=None,log=None):
    if deadline is None:
        deadline=time.time()+18
    def remaining(): return max(1,deadline-time.time())
    try:
        html=fetch_html(url,timeout=min(7,remaining()))
    except Exception as e:
        _log_fetch_failure(log,url,e)
        raise
    text,links=parse_html(html); host=urlparse(url).hostname or ""
    _log_fetch_success(log,url,len(text))
    pages=[url]; chunks=[text]; cands=[]
    for href in links:
        full=urljoin(url,href).split("#")[0]
        if same_domain(full,host) and relevant(full) and full not in cands and full!=url: cands.append(full)
    if len(cands)<max_extra_pages and time.time()<deadline:
        try:
            for u in discover_sitemap_urls(url,deadline=deadline):
                if relevant(u) and u not in cands and u!=url: cands.append(u)
                if len(cands)>=max_extra_pages*2: break
        except Exception: pass
    if len(cands)<3:
        scheme=urlparse(url).scheme or 'https'
        for path in COMMON_PUBLIC_PATHS:
            guess=f'{scheme}://{host}{path}'
            if guess not in cands and guess!=url: cands.append(guess)
    # v56: prioritise .pdf candidates (annual/CSR/ESG/sustainability reports) within the
    # existing relevance-filtered candidate list -- these are the company's own formal
    # reporting and are more likely to contain the kind of specific, substantiation-heavy
    # (or conspicuously unsubstantiated) claims that plain marketing pages do not.
    cands.sort(key=lambda u: 0 if u.lower().split('?')[0].endswith('.pdf') else 1)
    for i,link in enumerate(cands[:max_extra_pages]):
        if time.time()>=deadline: break
        if i>0 and remaining()>2: time.sleep(0.5)
        try:
            t,kind=fetch_page_content(link,timeout=min(8,remaining()))
            _log_fetch_success(log,link,len(t))
            # v57e/v57g: a PDF that yields *any* readable extracted text is already a much
            # stronger substance signal than an HTML page of the same length (successful text
            # extraction from a PDF rarely happens by accident) -- kept at 80 chars. The original
            # 200-char bar for HTML sub-pages had the same false-negative problem: a company's
            # actual sustainability/CSR sub-page is often short (one or two paragraphs) and was
            # being silently dropped exactly where the crawler most needs to reach it. Lowered to
            # 120, still enough to filter genuinely near-empty shell/loading pages.
            min_chars=80 if kind=="pdf" else 120
            if len(t)>min_chars:
                label="REPORT (PDF): " if kind=="pdf" else "PAGE: "
                chunks.append("\n\n"+label+link+"\n"+t); pages.append(link)
        except Exception as e:
            _log_fetch_failure(log,link,e)
    return "\n\n".join(chunks)[:90000], pages
COMPANY_SUFFIXES=r'(?:Corp\.?|Inc\.?|Ltd\.?|LLC|LLP|PLC|N\.?V\.?|S\.?A\.?|B\.?V\.?|GmbH|AG|SE|Group|Holdings?|Company|Co\.?|Limited)'
_COMPANY_NAME_RE=re.compile(r'\b([A-Z][A-Za-z0-9&\'\.\-]*(?:\s+[A-Z][A-Za-z0-9&\'\.\-]*){0,3}\s+'+COMPANY_SUFFIXES+r')\b')

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

def infer_company(url,text,company_name_hint=''):
    if company_name_hint and company_name_hint.strip():
        hint=company_name_hint.strip()
        combo=hint.lower()
        for k,p in PROFILES.items():
            if k in combo: return {"company":p[0],"sector":p[1],"sector_risk":p[2],"context":p[3]}
        return {"company":hint,"sector":"Sector not explicitly identified","sector_risk":"","context":"Company name provided by the user; context is based on document/website and external search signals."}
    combo=(url+" "+text[:5000]).lower()
    for k,p in PROFILES.items():
        if k in combo: return {"company":p[0],"sector":p[1],"sector_risk":p[2],"context":p[3]}
    host=urlparse(url).hostname or ""; name=host.replace("www.","").split(".")[0].title()
    if not name or not host:
        guessed=_guess_company_from_text(text)
        if guessed:
            return {"company":guessed,"sector":"Sector not explicitly identified","sector_risk":"","context":"Company name inferred from the uploaded document text; context is based on document content."}
    return {"company":name or "Company reviewed","sector":"Sector not explicitly identified","sector_risk":"","context":"No recognised company profile matched; context is based on website and external search signals."}
def infer_sector(company,text):
    if company.get("sector_risk"):
        level=company["sector_risk"]; basis="recognised company/sector profile"
    else:
        level="Medium"; basis="default medium exposure"; lower=(company.get("sector","")+" "+text[:15000]).lower()
        for lvl,terms,risks in SECTOR_RULES:
            hits=[t for t in terms if t in lower]
            if hits: level=lvl; basis="matched terms: "+", ".join(hits[:5]); break
    risks=next(r for lvl,terms,r in SECTOR_RULES if lvl==level)
    return {"level":level,"basis":basis,"risks":risks}
def tavily_search(q,max_results=5):
    if not TAVILY_API_KEY: return []
    payload={"query":q,"search_depth":"basic","max_results":max_results,"include_answer":False,"include_raw_content":False,"topic":"general"}
    req=Request("https://api.tavily.com/search",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+TAVILY_API_KEY},method="POST")
    with urlopen(req,timeout=7) as r: data=json.loads(r.read().decode("utf-8",errors="ignore"))
    return [{"title":i.get("title",""),"url":i.get("url",""),"content":i.get("content",""),"score":i.get("score",0),"published_date":i.get("published_date","")} for i in data.get("results",[])]

def google_search(query, max_results=5):
    """Google Custom Search JSON API fallback. Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return []
    from urllib.parse import urlencode
    params=urlencode({"key":GOOGLE_SEARCH_API_KEY,"cx":GOOGLE_SEARCH_CX,"q":query,"num":max(1,min(max_results,10))})
    req=Request("https://www.googleapis.com/customsearch/v1?"+params,headers={"User-Agent":CRAWLER_USER_AGENT},method="GET")
    with urlopen(req,timeout=7) as r:
        data=json.loads(r.read().decode("utf-8",errors="ignore"))
    out=[]
    for item in data.get("items",[]):
        out.append({"title":item.get("title",""),"url":item.get("link",""),"content":item.get("snippet",""),"score":0,"provider":"Google Custom Search"})
    return out

def search_public_sources(query,max_results=4):
    """Provider cascade: Tavily primary, Google Custom Search fallback."""
    attempts=[]
    if TAVILY_API_KEY:
        try:
            res=tavily_search(query,max_results)
            for r in res: r["provider"]="Tavily"
            attempts.append({"provider":"Tavily","status":"ok","results":len(res)})
            if res: return res,attempts
        except Exception as e:
            attempts.append({"provider":"Tavily","status":"failed","error":str(e)[:180]})
    else:
        attempts.append({"provider":"Tavily","status":"not_configured"})
    if GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX:
        try:
            res=google_search(query,max_results)
            attempts.append({"provider":"Google Custom Search","status":"ok","results":len(res)})
            if res: return res,attempts
        except Exception as e:
            attempts.append({"provider":"Google Custom Search","status":"failed","error":str(e)[:180]})
    else:
        attempts.append({"provider":"Google Custom Search","status":"not_configured"})
    return [],attempts

def query_themes_from_findings(findings):
    themes=set()
    joined=" ".join((f.get("type","")+" "+f.get("claim","")).lower() for f in (findings or []))
    if "supplier" in joined or "supply" in joined: themes.update(["supplier labour rights controversy", "forced labour supply chain", "audit failure worker voice remediation", "workers wage complaint", "NGO labour rights report", "EU forced labour regulation supply chain product import"])
    if "forced" in joined or "modern slavery" in joined: themes.update(["forced labour products regulation investigation", "modern slavery supply chain import ban", "forced labour product withdrawal customs EU"])
    if "human" in joined or "labour" in joined or "labor" in joined: themes.update(["human rights complaint", "labour rights lawsuit", "modern slavery forced labour", "workers rights NGO report"])
    if "diversity" in joined or "inclusion" in joined or "equality" in joined: themes.update(["discrimination lawsuit", "diversity inclusion controversy", "pay gap equal opportunity complaint"])
    if "safety" in joined or "worker" in joined or "welfare" in joined: themes.update(["worker safety accident", "union strike working conditions", "employee welfare complaint"])
    if "customer" in joined or "accessibility" in joined or "vulnerable" in joined: themes.update(["customer protection regulator complaint", "accessibility complaint", "vulnerable customers investigation"])
    if "community" in joined or "impact" in joined: themes.update(["community impact criticism", "affected communities complaint", "social impact controversy"])
    if not themes:
        themes.update(["social responsibility criticism", "human rights labour controversy", "workers supplier complaint"])
    return list(themes)[:8]

def external(company, findings=None):
    # V25: claim-specific external search. Queries are derived from the detected claim areas
    # so the public-source layer is less generic and better suited to contradiction testing.
    themes=query_themes_from_findings(findings or [])
    qs=[f'{company} {theme}' for theme in themes]
    qs.append(f'{company} social washing greenwashing misleading social claims')
    allr=[]; seen=set(); provider_attempts=[]; providers=set()
    for q in qs[:3]:
        res,attempts=search_public_sources(q,4)
        provider_attempts.extend([dict(a,query=q) for a in attempts])
        for r in res:
            u=r.get("url","")
            if u and u not in seen:
                r["query"]=q; r["credibility"]=source_credibility(r); allr.append(r); seen.add(u)
                if r.get("provider"): providers.add(r.get("provider"))
    if not TAVILY_API_KEY and not (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX):
        return {"enabled":False,"summary":"External public-source search is not enabled because neither TAVILY_API_KEY nor Google Custom Search credentials are configured.","results":[],"compact_sources":[],"providers_used":[],"provider_attempts":provider_attempts,"query_themes":themes}
    summary=summarise_ext(allr)
    if providers: summary += " Search provider(s) used: "+", ".join(sorted(providers))+"."
    else: summary += " No usable external results were returned by the configured providers."
    return {"enabled":True,"summary":summary,"results":allr[:20],"compact_sources":negative_compact_sources(allr,5),"providers_used":sorted(providers),"provider_attempts":provider_attempts,"query_themes":themes}

def summarise_ext(results):
    if not results: return "No external public-source results were returned."
    combo=" ".join((r.get("title","")+" "+r.get("content","")).lower() for r in results)
    terms=["forced labour","forced labor","EU forced labour regulation","product ban","import ban","child labour","child labor","lawsuit","complaint","strike","union","ngo","discrimination","human rights","supplier","workers","controversy","regulator","customs","withdrawal"]
    hits=[t for t in terms if t in combo]
    return ("External results contain potentially relevant social-risk signals, including: "+", ".join(hits[:8])+". These require verification.") if hits else "External results were found, but no strong social-risk signal was detected from snippets alone."
def infer_context(company,text,ext):
    combo=(company.get("context","")+" "+text[:20000]+" "+ext.get("summary","")).lower(); level="Medium" if "No recognised" not in company.get("context","") else "Low"
    high=["forced labour","forced labor","EU forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","living wage","lawsuit","strike","union","human rights complaint","discrimination","regulator"]
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
    return "Very high" if score>=90 else "High" if score>=75 else "Medium" if score>=45 else "Low"
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

    severe_terms = ["forced labour","forced labor","EU forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","human rights complaint","lawsuit","court","regulator","regulatory","discrimination","strike","union","living wage"]
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

def evidence_signal_score(page_text, findings):
    """
    V25: evidence is assessed only in the original crawled website text, not in generated
    recommendations. This avoids giving credit for wording that the tool itself produced.
    """
    text=(page_text or "").lower()
    if not text.strip() or (findings and findings[0].get("type","").lower().startswith("no major")):
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
    no_major = findings and findings[0].get("type","").lower().startswith("no major")
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

def source_credibility(result):
    text=(result.get("title","")+" "+result.get("url","")+" "+result.get("content","")).lower()
    if any(x in text for x in ["oecd","europa.eu",".gov","ilo.org","ohchr.org","un.org","regulator","authority","commission","court"]): return "High"
    if any(x in text for x in ["reuters","bbc","ft.com","guardian","bloomberg","amnesty","human rights watch","oxfam","clean clothes","ngo"]): return "Medium-high"
    if any(x in text for x in ["blog","forum","opinion"]): return "Low"
    return "Medium"

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
    return [{"claim_text":f.get("claim",""),"claim_type":f.get("type",""),"risk_level":f.get("risk",""),"claim_score":f.get("claim_score",0),"risk_reason":f.get("issue",""),"matched_phrase":f.get("matched_phrase",""),"why_flagged":f.get("why_flagged",""),"regulatory_signal":f.get("regulatory_signal",""),"specification_check":f.get("specification_check",{}),"pre_publication_decision":f.get("pre_publication_decision","Review before publication."),"evidence_needed":evidence_checklist(f),"suggested_rewrite":f.get("rewrite",""),"standards":f.get("standards",[]),"problematic_terms":f.get("problematic_terms",[])} for f in findings]

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
    if ext.get("enabled") and len(ext.get("results",[]))>=5: pts+=2; reasons.append("external public-source search returned several results")
    elif ext.get("enabled"): pts+=1; reasons.append("external public-source search was active")
    else: reasons.append("external public-source search was not active")
    no_findings=not findings or findings[0].get("type","").lower().startswith("no major")
    if not no_findings: pts+=1; reasons.append("claim-level signals were detected")

    # v56: fold crawl reliability into confidence instead of leaving it as a silent side-channel.
    # A scan that mostly failed or returned thin/blocked pages should not read the same as a
    # scan that genuinely reached the site and found little to flag.
    blocked=[e for e in (crawl_log or []) if not e.get("ok")]
    thin=[e for e in (crawl_log or []) if e.get("ok") and e.get("thin")]
    attempted=len(crawl_log or [])
    reliability_warning=None
    if attempted:
        failure_ratio=len(blocked)/attempted
        if failure_ratio>=0.5 or (len(pages)<=1 and blocked):
            pts=max(0,pts-2)
            reliability_warning=(f"{len(blocked)} of {attempted} page fetches failed (e.g. HTTP 403/blocked or unreachable). "
                                  "A low risk score from this scan may reflect limited access to the site's content, "
                                  "not necessarily a genuine absence of risky claims.")
        elif thin:
            pts=max(0,pts-1)
            reliability_warning=(f"{len(thin)} of {attempted} fetched page(s) returned unusually little text, which can happen "
                                  "with JavaScript-rendered pages or soft bot-blocks. Treat a low score with some caution and "
                                  "consider checking the site's sustainability/CSR pages manually.")
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
    result={"level":level_str,"reasons":reasons}
    if reliability_warning:
        result["reliability_warning"]=reliability_warning
    return result

def split_scores(findings,sector,context,external_modifier,score_components=None):
    if score_components:
        return {k:score_components[k] for k in ["claim_wording_risk","substantiation_risk","external_context_risk","sector_baseline_risk"] if k in score_components}
    claim=max(f.get("claim_score",0) for f in findings)
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
    serious_terms = ["forced labour","forced labor","EU forced labour regulation","product ban","import ban","customs","withdrawal","child labour","child labor","modern slavery","human rights","lawsuit","court","regulator","regulatory","discrimination","strike","union","living wage","complaint","oecd","ncp"]
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
        "formula": "Overall score = 30% claim wording risk + 30% substantiation/evidence-gap risk + 25% external contradictory-context risk + 15% sector sensitivity.",
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
    if findings and findings[0].get("type","").lower().startswith("no major"):
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

def source_mentions_company(result, company_name):
    text = (result.get("title","") + " " + result.get("content","") + " " + result.get("url","")).lower()
    terms = company_terms_for_filter(company_name)
    alias_map={
        'zara':['zara','inditex'], 'inditex':['inditex','zara','itx'],
        'delhaize':['delhaize','ahold delhaize','aholddelhaize'], 'lidl':['lidl','schwarz'],
        'aldi':['aldi'], 'kbc':['kbc'], 'proximus':['proximus'], 'fluxys':['fluxys']
    }
    expanded=[]
    for t in terms:
        expanded.append(t)
        for part in t.replace('/',' ').replace('-',' ').split():
            expanded.extend(alias_map.get(part,[]))
    expanded=list(dict.fromkeys([x for x in expanded if len(x)>=3]))
    return bool(expanded) and any(t in text for t in expanded)

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

def is_company_owned_source(result, company_name, reviewed_pages=None):
    """Exclude company-owned websites/documents from external public-source signals.
    Company sustainability reports, policies, supplier codes and own human-rights documents may be evidence,
    but they are not external stakeholder signals.
    """
    url=result.get('url','') or ''
    host=(urlparse(url).hostname or '').lower().replace('www.','')
    if not host: return False
    root=_root_domain(host)
    if root and root in company_owned_roots(reviewed_pages):
        return True
    terms=company_terms_for_filter(company_name)
    cleaned=[]
    for t in terms:
        t=t.lower().replace(' / ',' ').replace('/',' ').replace('-',' ').replace('&',' ')
        cleaned.extend([x for x in t.split() if len(x)>=3 and x not in {'group','company','holding','holdings','corporate'}])
    cleaned=list(dict.fromkeys(cleaned))
    host_labels=set(host.split('.'))
    host_compact=host.replace('-','').replace('_','').replace('.','')
    # Treat brand or parent-company domains as company-owned even when the brand is embedded
    # inside a larger host name (e.g. aholddelhaize.com, corporate.lidl.com).
    if any(t in host_labels for t in cleaned) or any(t.replace(' ','') in host_compact for t in cleaned):
        return True
    brand_aliases={
        'delhaize':['aholddelhaize','ahold','delhaize'],
        'lidl':['lidl','schwarz'],
        'aldi':['aldi'],
        'zara':['zara','inditex'],
        'inditex':['inditex','zara'],
        'kbc':['kbc'],
        'proximus':['proximus'],
        'fluxys':['fluxys']
    }
    alias_terms=[]
    for term in cleaned:
        alias_terms.extend(brand_aliases.get(term,[]))
    if any(a and a in host_compact for a in alias_terms):
        return True
    # Also exclude obvious company-hosted policy/report pages even where the host uses a country/corporate subdomain.
    text=(result.get('title','')+' '+result.get('content','')+' '+url).lower()
    own_doc_terms=['sustainability page','sustainability report','sustainability statement','annual report','annualreview','integrated report','esg report','non-financial report','csrd','esrs','human rights in the supply chain','human rights policy','human-rights policy','human rights statement','supplier code','supplier policy','supplier standards','code of conduct','modern slavery statement','due diligence statement','policy','policies','our responsibility','our sustainability','our human rights','supplier responsibility','corporate responsibility report','responsibility report','impact report','press release','news release','corporate news','annual results','quarterly results','rapport annuel','jaarverslag','duurzaamheidsverslag','rapport de durabilité']
    # External-stakeholder section must not include company-owned policies, reports,
    # own supplier codes, own sustainability pages or document repositories. These may
    # support evidence assessment elsewhere, but are not external public-source signals.
    company_source_markers=['official site','official website','corporate site','company website','corporate website','annualreports','reports.','cdn','assets','static','download','media','investor','investors','sustainability','responsibility','about-us','about us']
    if any(t in text for t in own_doc_terms) and (any(t in text for t in cleaned) or any(a in text for a in alias_terms)):
        return True
    if any(t in text for t in own_doc_terms) and any(m in host for m in company_source_markers):
        return True
    if any(a and a in host_compact for a in alias_terms+cleaned) and any(t in text for t in ['our ', 'we ', 'policy', 'report', 'statement', 'code', 'suppliers', 'sustainability']):
        return True
    # Search providers often return company PDFs from document/CDN hosts. Exclude them when title/snippet clearly indicates the source is the company itself.
    company_possessive=[f'{t} ' for t in cleaned]+[f'{a} ' for a in alias_terms]
    if any(t in text for t in own_doc_terms) and any(t.strip() in text for t in cleaned+alias_terms):
        return True
    return False

def targeted_negative_sources(results, company_name, limit=5, reviewed_pages=None, negative_fn=None):
    kept = []
    negative_fn = negative_fn or is_negative_external_source
    positive_markers = POSITIVE_NOISE_TERMS + ['annual report','sustainability report','esg report','policy','supplier code','code of conduct','our sustainability','our responsibility','press release','corporate news','investor relations','annual results','quarterly results','case study','best practice','ranked','awarded']
    hard_negative = ['greenwashing','misleading','complaint','lawsuit','court','investigation','probe','fine','penalty','sanction','regulator','authority','watchdog','accused','alleged','allegation','criticism','concern','concerns','criticised','criticized','forced labour','forced labor','child labour','child labor','modern slavery','human rights abuse','strike','union','protest','boycott','violation','breach','controversy','backlash','scandal']
    for r in results:
        text=(r.get('title','')+' '+r.get('content','')+' '+r.get('url','')).lower()
        if is_company_owned_source(r, company_name, reviewed_pages):
            continue
        if not source_mentions_company(r, company_name):
            continue
        # Only keep negative stakeholder perceptions. Positive corporate news, company documents and neutral announcements are excluded.
        if not any(n in text for n in hard_negative):
            continue
        if any(p in text for p in positive_markers) and not any(n in text for n in ['accused','alleged','allegation','criticism','criticised','criticized','complaint','lawsuit','court','regulator','fine','penalty','greenwashing','misleading','forced labour','forced labor','child labour','child labor','investigation','probe']):
            continue
        if negative_fn(r):
            kept.append(r)
    if "compact_sources" in globals():
        return compact_sources(kept, limit)
    return kept[:limit]

def reader_friendly_summary(company, sector, findings, external_research, score, score_components=None):
    name = company.get("company", "The company")
    sector_name = company.get("sector", "the identified sector")
    claim_findings = [f for f in findings if not f.get("type","").lower().startswith("no major")]
    first = claim_findings[0] if claim_findings else None
    targeted = targeted_negative_sources(external_research.get("results", []) if external_research else [], name, 5)
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
 {'name':'EU Forced Labour Regulation / Regulation (EU) 2024/3015 (core provisions apply from 14 December 2027)','use':'Main social-claim lens for forced-labour/traceability wording. Flags wording that may imply products, suppliers or value chains are free from forced labour, or that traceability, due diligence or import/export controls provide assurance beyond what is evidenced. It is a market-prohibition and customs-enforcement regime, not a claims law, and Art. 1(3) confirms it creates no new due-diligence obligation of its own -- readiness matters ahead of 2027, not an existing statutory breach today.'},
 {'name':'UCPD environmental-claim definition','use':'Checks whether text, images, symbols, labels, brand names, trade names or presentation imply positive, zero, reduced, comparative or improved environmental impact of a product, brand or trader.'},
 {'name':'Blacklisted-practices lens (Annex I)','use':'Flags high-sensitivity indicators that Annex I treats as unfair in all circumstances: generic environmental claims without recognised excellent environmental performance (4a), claiming an entire product/business benefit when only one aspect or activity is meant (4b), product-level claims of neutral/reduced/positive climate impact based on offsetting (4c), self-declared sustainability labels not based on a certification scheme or public authority (2a), and presenting a legal requirement as a distinctive feature (10a).'},
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
    """Return approximate text segment per crawled page so audience and claim-source links can be more precise."""
    pages=pages or []
    if not pages:
        return []
    text=full_text or ''
    segments=[]
    # First page is text before first PAGE marker.
    first=text.split('\n\nPAGE: ',1)[0]
    segments.append({'url':pages[0], 'text':first})
    for part in text.split('\n\nPAGE: ')[1:]:
        line, _, rest=part.partition('\n')
        url=line.strip()
        if url:
            segments.append({'url':url, 'text':rest})
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
        aud='Client-facing / consumer-facing communication'; emp='Direct / high'
        note='The reviewed material is mainly market-facing. Green claims should be assessed with stronger EmpCo-style consumer-communication controls.'
    elif counts.get('investor',0)>0 and counts.get('client_facing',0)==0:
        aud='Investor reporting'; emp='Indirect / evidence source'
        note='The reviewed material is mainly annual reports, sustainability reports, ESG reports or investor reporting. Treat it primarily as evidence or context, not as consumer advertising, unless the same claims are reused externally.'
    elif counts.get('internal',0)>0 and counts.get('client_facing',0)==0:
        aud='Policy / internal governance material'; emp='Indirect / governance evidence'
        note='The reviewed material appears to be policy or governance material. It is useful as substantiation evidence, but wording risk is lower than in consumer-facing material.'
    else:
        aud='Mixed channel set'; emp='Mixed'
        note='The scan includes more than one communication channel. The analysis separates client-facing communication from investor reporting and policy/internal governance material.'
    return {'audience':aud,'empco_relevance':emp,'note':note,'channel_counts':counts}


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
    aud=(audience or {}).get('audience','')
    for f in green_findings or []:
        if f.get('risk')=='High' and not f.get('type','').lower().startswith('no major'):
            green.append(f"{f.get('type','Green claim')} detected. Problematic trigger(s): {', '.join(f.get('problematic_terms',[])[:5]) or 'review wording'}. Source: {f.get('source_label') or f.get('source_url') or 'reviewed page/document'}.")
        if f.get('blacklisted_practice_indicator'):
            green.append(f.get('regulatory_signal','EmpCo readiness flag (applies from 27 September 2026).'))
    for f in social_findings or []:
        if f.get('risk')=='High' and not f.get('type','').lower().startswith('no major'):
            social.append(f"{f.get('type','Social claim')} detected. Source: {f.get('source_label') or f.get('source_url') or 'reviewed page/document'}. Evidence should cover scope, KPIs, limitations and remedy/traceability where relevant.")
    if (green_ext or {}).get('targeted_negative_sources'):
        green.append(f"External green public-source signals retained: {len((green_ext or {}).get('targeted_negative_sources',[]))}. Verify relevance and contradiction risk manually.")
    if (social_ext or {}).get('targeted_negative_sources'):
        social.append(f"External social public-source signals retained: {len((social_ext or {}).get('targeted_negative_sources',[]))}. Verify relevance and contradiction risk manually.")
    if not green: green.append('No separate green red flag was retained beyond normal evidence and wording review.')
    if not social: social.append('No separate social red flag was retained beyond normal evidence and wording review.')
    return {'green':list(dict.fromkeys(green))[:8], 'social':list(dict.fromkeys(social))[:8]}


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
        return 'High-priority EmpCo blacklisted-practice indicator where product-level neutral/reduced/positive climate impact is based on offsetting.'+date_note
    if 'label' in t or 'certification' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the label/badge is self-declared and not based on an independent certification scheme or public authority.'+date_note
    if 'generic environmental' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the generic claim is not clearly specified on the same medium and not backed by recognised excellent environmental performance.'+date_note
    if 'legal requirement' in t:
        return 'EmpCo blacklisted-practice indicator if legal compliance is presented as a distinctive environmental benefit.'+date_note
    if 'absolute' in t:
        return 'High overstatement indicator; can become misleading where the absolute claim is not fully substantiated for the full scope implied.'
    if 'comparative' in t:
        return 'High-risk comparison indicator where comparison method, comparator, source data and update process are missing.'
    return 'No direct blacklisted-practice indicator identified, but claim-specific substantiation is still required.'

def green_specification_check(claim_type, claim_text):
    c=(claim_text or '').lower(); t=(claim_type or '').lower()
    specificity_terms=['%', 'scope', 'baseline', 'compared with', 'compared to', 'made from', 'verified', 'certified', 'according to', 'methodology', 'life cycle', 'lca', 'for this product', 'packaging', 'valid until', 'standard', 'iso']
    has_specific=any(x in c for x in specificity_terms) or bool(re.search(r'\b\d{1,4}(?:[.,]\d+)?\s?%\b', c))
    if t.startswith('no major'):
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
        return common+['Is the label/badge independent or self-declared?','What scheme owner, criteria, audit process and validity period apply?','Could the visual presentation imply a broader benefit than the evidence supports?']
    if 'future' in t:
        return common+['Is there a public implementation plan with milestones, resources and governance?','Is progress independently verified and reported?']
    if 'comparative' in t:
        return common+['What comparator is used?','Are products/suppliers compared on an equivalent basis?','How is the comparison kept up to date?']
    if 'legal requirement' in t:
        return common+['Is the statement merely legal compliance?','Is it presented separately from voluntary sustainability performance?']
    return common

def enrich_green_finding(f, trigger=''):
    f['module']=green_claim_module(f.get('type',''))
    f['regulatory_signal']=green_blacklisted_indicator(f.get('type',''), trigger, f.get('claim',''))
    sig=f['regulatory_signal'].lower(); f['blacklisted_practice_indicator']=(('blacklisted-practice indicator' in sig) and not sig.startswith('no direct'))
    f['specification_check']=green_specification_check(f.get('type',''), f.get('claim',''))
    f['evidence_questions']=green_claim_evidence_questions(f.get('type',''))
    f['pre_publication_decision']='Do not publish/reuse without legal/compliance and evidence review.' if f.get('risk')=='High' and not f.get('type','').lower().startswith('no major') else 'Can normally proceed only after standard evidence and wording review.'
    return f


def green_query_themes(findings):
    joined=' '.join((f.get('type','')+' '+f.get('claim','')).lower() for f in findings or [])
    themes=[]
    if 'climate' in joined or 'carbon' in joined or 'net zero' in joined: themes += ['greenwashing carbon neutral offset claim','net zero misleading advertising complaint']
    if 'generic' in joined or 'sustainable' in joined: themes += ['greenwashing sustainable claim advertising regulator','misleading environmental claim complaint']
    if 'comparative' in joined or 'lower' in joined: themes += ['misleading lower emissions comparison complaint','environmental comparison advertising claim']
    if 'label' in joined or 'certification' in joined: themes += ['sustainability label misleading certification complaint','eco label greenwashing']
    if 'circular' in joined or 'recycl' in joined or 'durab' in joined: themes += ['recyclable claim greenwashing complaint','circularity claim misleading advertising']
    if not themes: themes=['greenwashing misleading environmental claims complaint']
    return list(dict.fromkeys(themes))[:8]

def external_green(company, findings=None):
    themes=green_query_themes(findings or [])
    qs=[f'{company} {theme}' for theme in themes]
    allr=[]; seen=set(); provider_attempts=[]; providers=set()
    for q in qs[:3]:
        res,attempts=search_public_sources(q,4)
        provider_attempts.extend([dict(a,query=q) for a in attempts])
        for r in res:
            u=r.get('url','')
            if u and u not in seen:
                r['query']=q; r['credibility']=source_credibility(r); allr.append(r); seen.add(u)
                if r.get('provider'): providers.add(r.get('provider'))
    if not TAVILY_API_KEY and not (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX):
        return {'enabled':False,'summary':'External public-source search is not enabled because neither TAVILY_API_KEY nor Google Custom Search credentials are configured.','results':[],'compact_sources':[],'providers_used':[],'provider_attempts':provider_attempts,'query_themes':themes}
    summary=summarise_green_ext(allr)
    if providers: summary += ' Search provider(s) used: '+', '.join(sorted(providers))+'.'
    else: summary += ' No usable external results were returned by the configured providers.'
    return {'enabled':True,'summary':summary,'results':allr[:20],'compact_sources':green_negative_compact_sources(allr,5),'providers_used':sorted(providers),'provider_attempts':provider_attempts,'query_themes':themes}

def summarise_green_ext(results):
    if not results: return 'No external public-source results were returned.'
    combo=' '.join((r.get('title','')+' '+r.get('content','')).lower() for r in results)
    terms=['greenwashing','misleading','advertising','regulator','complaint','lawsuit','court','authority','carbon neutral','offset','sustainable','recyclable','environmental claim']
    hits=[t for t in terms if t in combo]
    return ('External results contain potentially relevant green-claim signals, including: '+', '.join(hits[:8])+'. These require verification.') if hits else 'External results were found, but no strong green-claim risk signal was detected from snippets alone.'

GREEN_NEGATIVE_SIGNAL_TERMS=['greenwashing','misleading','complaint','lawsuit','court','regulator','authority','advertising standards','ban','prohibited','investigation','fine','penalty','sanction','watchdog','accused','allegation','criticised','criticized','consumer authority','settlement','asa','jep']


def green_evidence_signal_score(page_text, findings):
    text=(page_text or '').lower()
    if not text.strip() or (findings and findings[0].get('type','').lower().startswith('no major')):
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
    no_major=findings and findings[0].get('type','').lower().startswith('no major')
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
        out.append({'dimension':'Green','claim_text':f.get('claim',''),'claim_type':f.get('type',''),'washing_type':f.get('type',''),'risk_level':f.get('risk',''),'claim_score':f.get('claim_score',0),'module':f.get('module',green_claim_module(f.get('type',''))),'risk_reason':f.get('issue',''),'analysis':f.get('issue',''),'matched_phrase':f.get('matched_phrase',''),'why_flagged':f.get('why_flagged',''),'regulatory_signal':f.get('regulatory_signal',''),'blacklisted_practice_indicator':f.get('blacklisted_practice_indicator',False),'specification_check':f.get('specification_check',{}),'evidence_questions':f.get('evidence_questions',[]),'pre_publication_decision':f.get('pre_publication_decision','Review before publication.'),'evidence_needed':green_evidence_checklist(f),'suggested_rewrite':f.get('rewrite',''),'standards':f.get('standards',[]),'problematic_terms':f.get('problematic_terms',[])})
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
        r['dimension']='Social'; r['washing_type']=SOCIAL_WASHING_TAXONOMY.get(r.get('claim_type',''),r.get('claim_type',''))
    return rows

def build_green_social_actions(green_findings, social_findings, audience, company_name=''):
    actions=[]
    cn=(company_name or '').strip()
    who=cn if cn and cn.lower() not in ('company reviewed','') else 'the company'
    client_facing=('Client-facing' in audience.get('audience','') or 'Consumer-facing' in audience.get('audience','') or 'commercial' in audience.get('audience','').lower())
    all_findings=(green_findings or [])+(social_findings or [])
    high_green=[f for f in (green_findings or []) if f.get('risk')=='High']
    high_social=[f for f in (social_findings or []) if f.get('risk')=='High']
    claim_types='; '.join(dict.fromkeys([f.get('type','claim') for f in all_findings if f.get('type') and not f.get('type','').lower().startswith('no ')]))[:220]
    green_terms=list(dict.fromkeys([t for f in high_green for t in (f.get('problematic_terms') or [])]))[:5]
    social_terms=list(dict.fromkeys([t for f in high_social for t in (f.get('problematic_terms') or [])]))[:5]
    if client_facing or high_green:
        wording=f' Specific wording to check: {", ".join(green_terms)}.' if green_terms else ''
        actions.append({'priority':'Priority 1','title':'Review client-facing green claims under EmpCo','action':f"Check the exact wording {who} uses for the detected green claim areas ({claim_types or 'environmental claims'}) on websites/product pages/folders.{wording} For each claim, document scope, product coverage, methodology, evidence source, verification basis and limitations before reuse."})
    else:
        actions.append({'priority':'Priority 1','title':'Confirm which scanned claims are client-facing','action':f'Separate {who}\'s website/product/folder wording from annual or sustainability report language. Treat client-facing claims as higher priority for EmpCo-style substantiation and approval controls.'})
    if high_social:
        forced=any(('forced' in f.get('type','').lower() or 'modern slavery' in f.get('type','').lower() or 'supply' in f.get('type','').lower()) for f in high_social)
        wording=f' Specific wording to check: {", ".join(social_terms)}.' if social_terms else ''
        if forced:
            actions.append({'priority':'Priority 2','title':'Validate forced-labour and supplier claims','action':f"For {who}'s supplier, responsible-sourcing, modern-slavery or forced-labour wording, prepare evidence on product/supplier traceability, risk assessment by geography/product, mitigation, grievance/remediation and withdrawal/customs response readiness ahead of Regulation (EU) 2024/3015's core provisions applying from 14 December 2027.{wording}"})
        else:
            actions.append({'priority':'Priority 2','title':'Substantiate high-priority social claims','action':f"For {who}'s detected social claim areas ({claim_types or 'social claims'}), collect stakeholder scope, KPIs, grievance/remedy evidence, audit or workforce data and clear limits to avoid overstatement.{wording}"})
    actions.append({'priority':'Priority 3','title':'Build a claim evidence file','action':'Create one evidence file per priority claim retained in this scan, with the approved wording, source URL/document, owner, evidence link, date, legal/compliance review status and review deadline.'})
    if any('comparative' in f.get('type','').lower() for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Check comparative green claims','action':f"For {who}'s reduced impact, lower emissions or better product wording, identify the comparator, baseline year, methodology, equivalent product basis and data date."})
    if any(('climate' in f.get('type','').lower() or 'offset' in f.get('type','').lower() or 'net zero' in f.get('claim','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Clarify climate and offset claims','action':f"Separate {who}'s actual emission reductions from offsetting/compensation, and disclose scopes, baseline, residual emissions, implementation plan and progress indicators."})
    if any(('label' in f.get('type','').lower() or 'certification' in f.get('type','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Verify labels and certifications','action':f"Name the scheme owner, criteria, certification scope, verification body and validity period for any green/social label or certification {who} references."})
    actions.append({'priority':'Priority 5','title':'Align reporting and marketing language','action':f"Use {who}'s sustainability and annual reports as supporting evidence, but avoid copying broad report language into consumer-facing pages unless the claim is specific, current, substantiated and audience-appropriate."})
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
        vals=[f.get('type','claim') for f in fs or [] if not f.get('type','').lower().startswith('no major') and not f.get('type','').lower().startswith('no material')]
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
        return 'low' if n<45 else 'medium' if n<75 else 'high' if n<90 else 'very high'
    def dominant_driver(splits):
        labels={'claim_wording_risk':'the wording of the claims themselves','substantiation_risk':'a lack of visible evidence/substantiation','external_context_risk':'negative external signals','sector_baseline_risk':'sector-level exposure'}
        best=max(labels, key=lambda k: (splits or {}).get(k,0))
        return labels[best], (splits or {}).get(best,0)
    gnames=claim_names(green_fs); snames=claim_names(social_fs)
    g_top, g_top_val = dominant_driver(green_splits)
    s_top, s_top_val = dominant_driver(social_splits)
    audience_note='This is client/consumer-facing material, which increases EmpCo relevance.' if 'Client-facing' in audience.get('audience','') else 'This is investor/internal material, treated mainly as evidence and consistency context rather than a direct consumer claim.'
    g_ext_n=targeted_count(green_ext); s_ext_n=targeted_count(social_ext)
    if gnames:
        g_summary=f'Green score is {green_score}/100 ({band(green_score)} risk), mainly because of {g_top} ({g_top_val}/100). Claim types retained: {", ".join(gnames[:3])}.'
        if g_ext_n: g_summary+=f' {g_ext_n} external green signal(s) were also factored in.'
    else:
        g_summary=f'Green score is {green_score}/100 ({band(green_score)} risk). No material green claim was retained, so the score reflects only baseline sector exposure and any external context.'
    if snames:
        s_summary=f'Social score is {social_score}/100 ({band(social_score)} risk), mainly because of {s_top} ({s_top_val}/100). Claim types retained: {", ".join(snames[:3])}.'
        if s_ext_n: s_summary+=f' {s_ext_n} external social signal(s) were also factored in.'
    else:
        s_summary=f'Social score is {social_score}/100 ({band(social_score)} risk). No material social claim was retained, so the score reflects only baseline sector exposure and any external context.'
    return {
        'green': {
            'score': green_score,
            'summary': f'{g_summary} {audience_note}',
            'key_drivers': [
                f'Claim types detected: {", ".join(gnames) if gnames else "none material"}.',
                f'Strongest driver: {g_top} ({g_top_val}/100).',
                f'Evidence-gap level: {green_splits.get("substantiation_risk",0)}/100.',
                f'External green signals retained after company-owned-source filtering: {g_ext_n}.',
                f'Sector exposure for environmental claims: {sector.get("level","Medium")}.'
            ]
        },
        'social': {
            'score': social_score,
            'summary': f'{s_summary} Forced-labour or product/supply-chain wording receives higher regulatory weight where relevant.',
            'key_drivers': [
                f'Claim types detected: {", ".join(snames) if snames else "none material"}.',
                f'Strongest driver: {s_top} ({s_top_val}/100).',
                f'Evidence-gap level: {social_splits.get("substantiation_risk",0)}/100.',
                f'External social signals retained after company-owned-source filtering: {s_ext_n}.',
                f'Sector exposure for social claims: {sector.get("level","Medium")}.'
            ]
        }
    }


def extract_docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts=[]
        for name in ['word/document.xml']+[n for n in z.namelist() if n.startswith('word/header') or n.startswith('word/footer')]:
            try:
                xml=z.read(name).decode('utf-8',errors='ignore')
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
                decompressed=zlib.decompress(m.group(1))
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
        if f.get('type','').lower().startswith('no major'):
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
        if f.get('type','').lower().startswith('no major'):
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
    return {
        'audience':aud,
        'empco_blacklisted_indicator_count':len(green_flags),
        'forced_labour_indicator_count':len(social_flags),
        'highest_priority':'EmpCo blacklisted-practice review' if green_flags else ('Forced Labour Regulation / social-claims review' if social_flags else 'Standard substantiation review'),
        'empco_indicators':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim',''), 'signal':f.get('regulatory_signal','')} for f in green_flags[:8]],
        'forced_labour_or_social_indicators':[{'claim_type':f.get('type',''), 'claim_excerpt':f.get('claim',''), 'signal':'Check product/supplier traceability, forced-labour risk assessment, remediation and response readiness.'} for f in social_flags[:8]],
        'note':'This is a screening signal. It does not establish a legal breach, but it identifies claims that should be reviewed before publication or reuse.'
    }

def build_claim_modules_summary(green_findings, social_findings):
    modules={}
    for f in green_findings or []:
        m=f.get('module', green_claim_module(f.get('type','')))
        modules.setdefault(m, {'count':0,'risk_levels':[],'claim_types':[]})
        modules[m]['count']+=1; modules[m]['risk_levels'].append(f.get('risk','')); modules[m]['claim_types'].append(f.get('type',''))
    if social_findings and not social_findings[0].get('type','').lower().startswith('no major'):
        modules.setdefault('Social Washing Claim Check', {'count':0,'risk_levels':[],'claim_types':[]})
        for f in social_findings:
            modules['Social Washing Claim Check']['count']+=1; modules['Social Washing Claim Check']['risk_levels'].append(f.get('risk','')); modules['Social Washing Claim Check']['claim_types'].append(f.get('type',''))
    out=[]
    for m,v in modules.items():
        out.append({'module':m,'detected_claims':v['count'],'highest_risk':'High' if 'High' in v['risk_levels'] else ('Medium' if 'Medium' in v['risk_levels'] else 'Low'),'claim_types':list(dict.fromkeys(v['claim_types']))[:5]})
    return out

def federation_pilot_output(green_findings, social_findings, overall, green_score, social_score):
    return {
        'member_scan_positioning':'Sustainability Scan',
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
    sec=infer_sector(comp,text)
    ctx=infer_context(comp,text,social_ext)
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext,text,comp.get("company",""))
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext,text,audience)
    social_splits=split_scores(social_fs,sec,ctx,social_mod,social_components)
    green_splits={k:green_components[k] for k in ['claim_wording_risk','substantiation_risk','external_context_risk','sector_baseline_risk']}
    overall=combine_green_social(green_score,social_score,audience)
    all_claims=build_green_claim_inventory(green_fs)+social_claim_inventory_with_dimension(social_fs)
    for c in all_claims:
        c.setdefault('source_url', source); c.setdefault('source_label', filename or 'Uploaded document'); c.setdefault('audience_lens', audience.get('audience','Internal document')); c.setdefault('audience_group', audience.get('group','internal'))
    green_conclusion=green_washing_conclusion(green_score,green_fs,green_splits.get('substantiation_risk',50),green_splits.get('external_context_risk',0),audience)
    social_conclusion=washing_conclusion(social_score,social_fs,social_splits.get('substantiation_risk',50),social_splits.get('external_context_risk',0))
    methodology='Sustainability Scan. This is a separate internal-document scan. The uploaded file is assessed on its own and is not combined with website content or external public-source search. Internal documents are assessed mainly for claim wording, substantiation gaps, governance evidence, consistency risks and potential future reuse in client-facing communication. Scores use a continuous calibrated calculation method: claim wording, evidence gap, retained external stakeholder context, sector/channel sensitivity and direct EmpCo or Forced Labour Regulation indicators.'
    summary=f"{comp['company']} receives a global sustainability scan score of {overall}/100 for the uploaded internal document. Green risk: {green_score}/100 ({green_conclusion}). Social risk: {social_score}/100 ({social_conclusion})."
    return {'version':APP_VERSION,'source_label':source,'original_url':source,'fallback_note':'','analysis_date':datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
        'overall_score':overall,'overall_risk':level(overall),'global_score':overall,'global_risk':level(overall),'green_score':green_score,'green_risk':level(green_score),'green_conclusion':green_conclusion,'social_score':social_score,'social_risk':level(social_score),'social_conclusion':social_conclusion,'screening_conclusion':f'Global: {level(overall)} | Green: {level(green_score)} | Social: {level(social_score)}','methodology':methodology,'company':comp,'sector':sec,'context':ctx,'document_audience':audience,'findings':all_claims,'green_findings':green_fs,'social_findings':social_fs,'documents_checked':documents_checked,'channel_analysis':build_channel_analysis(documents_checked),'related_source_notes':[],'report':{'summary':summary,'rationale':methodology,'rewrite_guidance':'Make green and social claims specific, scoped, evidenced and audience-appropriate.','pages_reviewed':[source],'standards_overview':EMPCO_LENS+STANDARDS},'assessment_summary_specific':summary,'concise_standards_lens':EMPCO_LENS,'merged_claims':all_claims,'claim_inventory':all_claims,'regulatory_risk_summary':build_regulatory_risk_summary(green_fs,social_fs,audience),'claim_modules_summary':build_claim_modules_summary(green_fs,social_fs),'federation_pilot_output':federation_pilot_output(green_fs,social_fs,overall,green_score,social_score),'external_research':{'green':dict(green_ext,compact_sources=green_targeted,targeted_negative_sources=green_targeted),'social':dict(social_ext,compact_sources=social_targeted,targeted_negative_sources=social_targeted),'summary':'Internal-document scan only. No public-source or website content is included.'},'green_external_context_assessment':green_external_context,'social_external_context_assessment':{'score':0,'note':'Not assessed for internal-document scans.'},'score_components':{'green':green_components,'social':social_components},'split_scores':{'global_score':overall,'green_risk_score':green_score,'social_risk_score':social_score,'green':green_splits,'social':social_splits},'why_score':{'global':f'Global score is {overall}/100. It reflects only the uploaded internal document and is a weighted combination of the green and social scores.','green':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['green']['summary'],'social':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['social']['summary'],'audience':audience.get('note',''),'interpretation':'This is an assessment signal, not a legal finding.'},'score_driver_details':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext,sec,ctx)+(['EmpCo readiness flag (applies from 27 September 2026): high-sensitivity green claims should be prepared for EmpCo-style substantiation and wording controls ahead of that date.'] if any(f.get('risk')=='High' for f in green_fs) else []),'red_flags_by_dimension':split_red_flags_by_dimension(green_fs,social_fs,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'company_action_plan':build_green_social_actions(green_fs,social_fs,audience,comp.get('company','')),'engagement_questions':build_engagement_questions(social_fs,social_ext),'confidence':{'level':'Medium','reasons':['Uploaded document was scanned as a standalone source.','External public-source search was not performed for this internal-document scan.']},'disclaimer':'Indicative first-pass sustainability claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use.','analysed_text_excerpt':text[:2200],'quality_improvements':['Maintain a sustainability claims register distinguishing green and social claims, claim owner, evidence file and review date.','Attach objective evidence, same-medium specification, methodology, limitations and approval owner to each claim.'],'ai_used':False,'ai_note':''}

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
    scan_deadline=time.time()+18
    try:
        txt,pages,related_notes,crawl_log=crawl_with_related_sites(original_url,overall_deadline=scan_deadline); url=original_url
    except Exception as first_error:
        fallback_url=replace_tld_with_be(original_url)
        if fallback_url:
            try:
                txt,pages,related_notes,crawl_log=crawl_with_related_sites(fallback_url,overall_deadline=scan_deadline); url=fallback_url; fallback_note=(fallback_note+' ' if fallback_note else '')+f'The original website was not accessible. The scan was automatically performed on {fallback_url}.'
            except Exception as second_error:
                raise ValueError(f'Could not access {original_url} ({_describe_fetch_error(first_error)}) and the {fallback_url} fallback also failed ({_describe_fetch_error(second_error)}).')
        else:
            raise ValueError(f'Could not scan {original_url}: {_describe_fetch_error(first_error)}')
    comp=infer_company(url,txt)
    page_segments=extract_page_segments(txt,pages)
    audience=classify_document_audience(url,txt,pages)
    documents_checked=build_documents_checked(pages,audience,txt)
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
    social_ext=external(comp['company'], social_fs)
    green_ext=external_green(comp['company'], green_fs)
    exttext=' '.join(r.get('title','')+' '+r.get('content','') for r in (social_ext.get('results',[])+green_ext.get('results',[])))
    sec=infer_sector(comp,txt+'\n'+exttext)
    ctx=infer_context(comp,txt,social_ext)
    social_targeted=targeted_negative_sources(social_ext.get('results',[]), comp.get('company',''), 5, [d.get('url') for d in documents_checked], is_negative_external_source)
    green_targeted=targeted_negative_sources(green_ext.get('results',[]), comp.get('company',''), 5, [d.get('url') for d in documents_checked], is_green_negative_source)
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
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext_scoring,txt,comp.get("company",""))
    social_external_context = strict_external_context_risk({'results':social_targeted}, comp.get('company',''))
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext_scoring,txt,audience)
    overall=combine_green_social(green_score,social_score,audience)
    social_splits=split_scores(social_fs,sec,ctx,social_mod,social_components)
    green_splits={k:green_components[k] for k in ['claim_wording_risk','substantiation_risk','external_context_risk','sector_baseline_risk']}
    social_conclusion=washing_conclusion(social_score,social_fs,social_splits.get('substantiation_risk',50),social_splits.get('external_context_risk',0))
    green_conclusion=green_washing_conclusion(green_score,green_fs,green_splits.get('substantiation_risk',50),green_splits.get('external_context_risk',0),audience)
    all_claims=build_green_claim_inventory(green_fs)+social_claim_inventory_with_dimension(social_fs)
    all_claims=assign_claim_sources(all_claims,page_segments,documents_checked)
    for c in all_claims:
        c.setdefault('source_url', url)
        c.setdefault('source_label', 'Reviewed website / document')
        c.setdefault('audience_lens', audience.get('audience','Mixed or unclear'))
        c.setdefault('audience_group', 'mixed')
    methodology='Sustainability Scan. The assessment separates green and social claim signals. Green claims are assessed through an EmpCo / Directive (EU) 2024/825 lens for consumer-facing environmental claims (Member States must transpose by 27 March 2026; rules apply from 27 September 2026), with explicit modules for generic claims, carbon/offsetting, labels/icons, future claims, comparisons, legal-requirement claims and same-medium specification. Social claims are assessed through claim wording, evidence gap, external contradictory context and sector exposure, with a specific Forced Labour Regulation / Regulation (EU) 2024/3015 lens for product, supplier, import/export, traceability, forced-labour and modern-slavery claims (core prohibition and enforcement provisions apply from 14 December 2027; this is a market-access/customs regime, not a claims law, and creates no new due-diligence obligation of its own per Art. 1(3)). Clear indications of EmpCo or Forced Labour Regulation risk receive a higher weighting than broader responsible-business claims mainly linked to OECD Guidelines, UNGC or UNGP expectations. External public-source signals exclude company-owned websites, policies, reports and supplier documents; those may be used as evidence but not as external stakeholder signals. Sector exposure is included as a baseline sensitivity factor but should not create a High-risk result without problematic claim wording, evidence gaps or contradictory context.'
    confidence_result=build_confidence(pages,social_ext,social_fs,crawl_log)
    reliability_warning=confidence_result.get('reliability_warning')
    crawl_pages_attempted=len(crawl_log); crawl_pages_failed=len([e for e in crawl_log if not e.get('ok')])
    crawl_pages_thin=len([e for e in crawl_log if e.get('ok') and e.get('thin')])
    # v57p: always state coverage in plain terms -- pages reviewed, domains covered, how many
    # fetch attempts failed, and a standing caveat that JavaScript-rendered content may not have
    # been captured (this crawler reads server-rendered HTML/PDF text only). A low score should
    # never be presented as if it came from a complete site review when it did not.
    domains_covered=len({(urlparse(p).hostname or '') for p in pages if p})
    coverage_note=f"Coverage: {len(pages)} page(s) reviewed across {max(1,domains_covered)} domain(s)."
    if crawl_pages_failed:
        coverage_note+=f" {crawl_pages_failed} of {crawl_pages_attempted} page fetch attempt(s) could not be accessed."
    if crawl_pages_thin:
        coverage_note+=f" {crawl_pages_thin} page(s) returned unusually little text; JavaScript-rendered content may not have been fully captured."
    summary=(f"{comp['company']} receives a global sustainability scan score of {overall}/100. "
             f"Green risk: {green_score}/100 ({green_conclusion}). Social risk: {social_score}/100 ({social_conclusion}). "
             f"Document/channel classification: {audience['audience']}  -  {audience['note']}" + (" "+"; ".join(related_notes) if related_notes else "")
             + " " + coverage_note)
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
        'crawl_diagnostics':{'pages_attempted':crawl_pages_attempted,'pages_failed':crawl_pages_failed,'pages_thin':crawl_pages_thin,'detail':crawl_log},
        'methodology':methodology,'company':comp,'sector':sec,'context':ctx,'document_audience':audience,
        'findings':all_claims,'green_findings':green_fs,'social_findings':social_fs,
        'documents_checked':documents_checked,'channel_analysis':channel_analysis,'related_source_notes':related_notes,
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
        'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext,sec,ctx)+(['EmpCo readiness flag (applies from 27 September 2026): high-sensitivity, consumer-facing green claims should be prepared for EmpCo-style substantiation and wording controls ahead of that date.'] if any(f.get('risk')=='High' for f in green_fs) else []),
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
        if f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'):
            continue
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('regulatory_signal','')).lower()
        if any(x in t for x in ['generic environmental','climate-neutrality','offsetting','comparative environmental','future environmental','sustainability label','absolute or purity','legal requirement']):
            return True
    return False

def has_forced_labour_regulatory_signal(findings):
    for f in findings or []:
        if f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'):
            continue
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('analysis','')).lower()
        if any(x in t for x in ['forced labour','forced-labour','forced labor','modern slavery','child labour','child labor','traceability','import controls','supplier traceability']):
            return True
    return False

def recalibrate_dimension_score(raw_score, components, findings, targeted_sources, regulatory_signal=False, dimension='green'):
    """Material-claim scoring.

    The score measures risk intensity, not the number of sustainability words. It is
    conservative: isolated wording without weak substantiation and external negative
    stakeholder signals normally remains low to medium. High scores require multiple
    material claim signals, a major evidence gap, direct EmpCo / Forced Labour relevance
    or retained negative external stakeholder signals.
    """
    comps=dict(components or {})
    evidence_gap=int(comps.get('substantiation_risk',0) or 0)
    claim_wording=int(comps.get('claim_wording_risk',0) or 0)
    sector_score=int(comps.get('sector_baseline_risk',0) or 0)
    findings=list(findings or [])
    material=[f for f in findings if not (f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'))]
    material_count=len(material)
    high_claims=len([f for f in material if f.get('risk')=='High'])
    ext_count=len(targeted_sources or [])
    external_context=min(100, 18 + 14*ext_count) if ext_count else 0
    comps['external_context_risk']=external_context

    # Base weights. Claim wording and evidence gap are primary; sector is a modest
    # sensitivity factor; negative external signals can materially lift the result.
    base=round(claim_wording*0.30 + evidence_gap*0.30 + external_context*0.25 + sector_score*0.15)
    if regulatory_signal:
        base += 5 if dimension=='green' else 4
    if material_count>=2:
        base += min(6, (material_count-1)*3)
    if ext_count>=2:
        base += 4

    # Conservative caps for limited evidence of actual claim risk.
    if material_count==0:
        base=min(base, 18 + min(8, ext_count*3) + (4 if sector_score>=55 else 0))
    elif material_count==1 and ext_count==0:
        base=min(base, 52 if regulatory_signal else 45)
    elif material_count<=2 and ext_count==0:
        base=min(base, 60 if regulatory_signal else 54)
    elif material_count==1 and ext_count==1:
        base=min(base, 62 if regulatory_signal else 56)

    # Extremely high scores require a convergence of factors, not just one phrase.
    if base>=70 and not (evidence_gap>=60 and claim_wording>=58 and (ext_count>=1 or regulatory_signal or high_claims>=2) and material_count>=1):
        base=66
    if base>=80 and not (evidence_gap>=72 and claim_wording>=68 and ext_count>=2 and material_count>=2):
        base=76
    if base>=90 and not (ext_count>=3 and material_count>=3 and evidence_gap>=80):
        base=84

    base=max(0,min(100,int(round(base))))
    comps['score_calculation_note']='Score calculation: material problematic claim wording, evidence gap, retained negative external stakeholder context and sector/channel sensitivity. Isolated claim signals are treated as limited concerns unless supported by stronger regulatory relevance or retained negative external stakeholder context.'
    return base, comps



# Stricter negative-stakeholder source filters: company-owned documents, positive news,
# awards, partnerships and neutral corporate announcements are never retained.
def is_negative_external_source(result):
    text=_external_signal_text(result)
    hard_negative=['forced labour','forced labor','child labour','child labor','modern slavery','lawsuit','court','complaint','controversy','strike','union','regulator','regulatory','discrimination','human rights abuse','labour rights abuse','labor rights abuse','investigation','probe','fine','sanction','breach','violation','misconduct','unsafe','audit failure','accused','alleged','allegation','criticism','criticised','criticized','backlash','boycott','protest']
    stakeholder_context=['ngo','union','court','regulator','authority','watchdog','complaint','lawsuit','investigation','press','media','reuters','bbc','guardian','ft.com','oecd','ncp','amnesty','human rights watch','clean clothes']
    positive_or_owned=any(t in text for t in OWNED_OR_NEUTRAL_DOC_TERMS+POSITIVE_NOISE_TERMS+['press release','corporate news','award','recognised','recognized','partnership','launches','sustainability report','annual report','policy','supplier code','code of conduct'])
    return any(t in text for t in hard_negative) and any(t in text for t in stakeholder_context) and not positive_or_owned

def is_green_negative_source(result):
    text=_external_signal_text(result)
    hard=['greenwashing','misleading environmental','misleading green','complaint','lawsuit','court','regulator','authority','advertising standards','ban','prohibited','investigation','fine','penalty','sanction','watchdog','accused','allegation','criticised','criticized','consumer authority','settlement','asa','jep']
    stakeholder=['regulator','authority','watchdog','court','complaint','lawsuit','investigation','media','press','ngo','consumer authority','asa','jep','reuters','guardian','bbc','ft.com']
    positive_or_owned=any(t in text for t in OWNED_OR_NEUTRAL_DOC_TERMS+POSITIVE_NOISE_TERMS+['press release','corporate news','award','recognised','recognized','partnership','launches','sustainability report','annual report','policy'])
    return any(t in text for t in hard) and any(t in text for t in stakeholder) and not positive_or_owned

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
    return [f for f in (findings or []) if not (f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'))]


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
    'we believe in a world where','we dream of a world where','on a journey towards','on our journey towards']
_SOCIAL_ASPIRATION_TOPICS=['living wage','living wages','human rights','fair wage','fair wages','decent work',
    'decent working conditions','good working conditions','safe working conditions','workers rights',"workers' rights",
    'worker rights','labour rights','labor rights','gender equality','equal opportunities','dignity',
    'respected','well-being of workers','wellbeing of workers','fair treatment','social justice','worker welfare',
    'workers welfare']

def _looks_like_aspirational_social_claim(excerpt):
    c=(excerpt or '').lower()
    if not any(v in c for v in _ASPIRATIONAL_SOCIAL_VERBS):
        return False
    return any(t in c for t in _SOCIAL_ASPIRATION_TOPICS)

def _social_claim_context(excerpt, typ, trigger):
    c=(excerpt or '').lower(); t=(typ or '').lower(); trig=(trigger or '').lower()
    if len(c.strip()) < 35:
        return False
    neutral_supplier_phrases=['backing british suppliers','supporting local suppliers','working with suppliers','our suppliers include','supplier list','become a supplier','contact suppliers','supplier portal']
    if any(p in c for p in neutral_supplier_phrases):
        # Keep only if the same passage also contains a clear assurance/control signal.
        strong=['audited','certified','compliant','comply','traceable','ethical sourcing','responsible sourcing','forced labour','forced labor','human rights','due diligence','modern slavery']
        if not any(s in c for s in strong):
            return False
    if 'supplier' in t or 'supply-chain' in t:
        strong=['all suppliers','100% of suppliers','audited','certified','compliant','comply','meet our standards','traceable','ethical sourcing','responsible sourcing','due diligence','human rights','forced labour','forced labor','modern slavery','supplier code compliance','tier 1','tier 2']
        return any(s in c for s in strong)
    if 'forced' in t:
        return any(s in c for s in ['forced labour','forced labor','modern slavery','child labour','child labor','traceability','import controls','product traceability','supplier traceability'])
    if 'human-rights' in t or 'labour-rights' in t or 'labor-rights' in t:
        return any(s in c for s in ['human rights','labour rights','labor rights','living wage','decent work','fair wages','worker rights','no discrimination','zero discrimination','equal pay'])
    if 'safety' in t:
        return any(s in c for s in ['zero harm','zero accidents','injury free','guaranteed safe','safe workplace guaranteed'])
    if 'diversity' in t or 'inclusion' in t:
        return any(s in c for s in ['100% inclusive','fully inclusive','guaranteed equal','no pay gap','zero pay gap','no discrimination','zero discrimination'])
    return True

# Better-balanced green claim taxonomy: includes plural/common variants while retaining only claim-like contexts.
GREEN_CLAIMS=[
 (['eco-friendly','environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','ecological','climate friendly','climate-friendly','green product','green products','green choice','eco choice','eco product','eco products','sustainable product','sustainable products','sustainable choice','sustainable collection','sustainable range','sustainable materials','100% sustainable','fully sustainable','natural product','natural products','biobased product','bio-based product'],'Generic environmental claim','High','EmpCo risk: generic environmental claims can be prohibited in consumer-facing communication where the claim is not clearly and prominently specified on the same medium or backed by recognised excellent environmental performance relevant to the claim as a whole.','Replace generic wording with a precise, evidence-backed claim stating the exact product attribute, scope, geography, methodology, period and limitations.'),
 (['carbon neutral','climate neutral','co2 neutral','co₂ neutral','net zero product','carbon negative','carbon positive','climate positive','carbon compensated','climate compensated','offset-based','offsetting','compensated emissions','reduced climate impact'],'Climate-neutrality or offsetting claim','High','EmpCo risk: product-level claims that state or imply neutral, reduced or positive climate impact based on greenhouse-gas offsetting are high-priority blacklisted-practice indicators.','Avoid product-level neutrality wording based on offsets. Separate actual emissions reductions from offsets and disclose scopes, baseline, methodology, residual emissions and progress.'),
 (['greener than','more sustainable than','more eco-friendly than','lower impact than','lowest emissions','best environmental','less harmful than','lower emissions than','reduced emissions compared','reduced impact compared','lower carbon than','less carbon than'],'Comparative environmental claim','High','EmpCo risk: environmental comparisons require information on the comparison method, comparator, products and suppliers compared, data sources and update process.','State the comparator, baseline, methodology, scope, data date and update mechanism; avoid vague superiority claims.'),
 (['eco label','ecolabel','sustainability label','self-declared sustainability label','green certified','eco certified','planet approved','responsible choice label','green badge','eco badge','sustainability badge','certified sustainable','sustainably certified'],'Sustainability label / certification claim','High','EmpCo risk: self-declared sustainability labels are blacklisted unless based on an independent, transparent certification scheme or public-authority label. Icons, symbols and trust marks may fall within this category.','Name the scheme owner, criteria, independence, audit basis, scope and validity period. Remove self-declared labels or clarify them as non-certification claims.'),
 (['we will be net zero','we aim to be net zero','we are working towards net zero','committed to net zero','net zero by 2030','net zero by 2040','net zero by 2050','climate positive by','carbon neutral by','climate neutral by','decarbonisation roadmap','decarbonization roadmap'],'Future environmental-performance claim','High','EmpCo risk: future environmental-performance claims require clear, objective, publicly available and verifiable commitments supported by a realistic implementation plan.','Add a public implementation plan, milestones, resources, governance, progress indicators, verification basis and scope limitations.'),
 (['all natural','100% natural','chemical free','zero impact','no impact','zero waste','waste free','pollution free','fully recyclable','100% recyclable','completely biodegradable','fully biodegradable','plastic free','100% recycled'],'Absolute or purity environmental wording','High','EmpCo risk: absolute environmental wording creates a high evidence burden and can mislead when scope, conditions or limitations are missing.','Qualify the claim and specify exact attribute, scope, conditions, test method, limitations and evidence.'),
 (['compliant with environmental law','meets legal requirements','according to legal standards','required by law','legal requirement','eu compliant','regulation compliant'],'Legal requirement presented as green benefit','High','EmpCo risk: presenting requirements imposed by law as a distinctive environmental feature is a blacklisted-practice indicator.','Do not present legal compliance as a differentiating sustainability benefit. Separate legal compliance from voluntary improvements.'),
 (['green leaf','leaf icon','tree icon','water drop','waterdrop','planet icon','earth icon','eco badge','green badge','environmental icon','recycled badge','sustainability badge'],'Visual green-claim indicator','Medium','EmpCo risk: pictorial, graphic or symbolic representations can imply environmental benefits and should be assessed like written claims.','Check whether the icon or badge implies a specific environmental benefit and connect it to clear, prominent and evidenced wording.'),
]

CLAIMS=[
 (['forced labour free','forced labor free','free from forced labour','free from forced labor','no forced labour','no forced labor','modern slavery free','child labour free','child labor free','no child labour','no child labor','forced labour due diligence','forced labor due diligence','product traceability','supplier traceability','import controls'],'Forced-labour product or supply-chain claim','High','Forced Labour Regulation risk: the wording may imply product, supplier or supply-chain assurance against forced labour. Such claims require strong traceability, risk assessment, mitigation, remediation and withdrawal/customs response readiness.','Scope the wording and disclose a risk-based due-diligence process, product/supplier traceability, escalation and remediation steps.'),
 (['all suppliers audited','all suppliers are audited','all suppliers certified','all suppliers are certified','all suppliers comply','all suppliers are compliant','all suppliers meet','100% of suppliers','fully traceable supply chain','fully audited supply chain','ethical sourcing','responsible sourcing','responsibly sourced','responsibly-sourced','ethically sourced','certified suppliers','audited suppliers','traceable suppliers','supplier code compliance','certified against our supplier code','comply with our supplier code'],'Supply-chain or supplier-responsibility claim','High','The wording may imply broad supplier control or responsible value-chain coverage. It is problematic where supplier tiers, audit quality, worker voice, findings and remediation are not clear.','Scope the claim to covered supplier tiers and disclose coverage, methodology, findings and corrective-action closure rates.'),
 (['human rights compliant','respect human rights across our value chain','protect human rights across our value chain','respect human rights in our supply chain','living wage across our supply chain','decent work guaranteed','guaranteed labour rights','guaranteed labor rights','fair wages across our supply chain','no discrimination','zero discrimination','equal pay guaranteed'],'Human-rights or labour-rights claim','High','The claim refers to sensitive rights topics and may overstate outcomes or control without due diligence, grievance channels, tracking and remedy.','State the due-diligence process, salient risks, coverage, grievance channels, tracking, limits and remediation process.'),
 (['safe workplace guaranteed','zero accidents','zero harm','injury free','guaranteed safe workplace','no workplace injuries'],'Health, safety or worker-welfare claim','High','Absolute safety or welfare wording creates a high evidence burden and can overstate outcomes, particularly where contractors or suppliers are involved.','Use scoped wording linked to incident data, controls, coverage, training and corrective actions.'),
 (['all employees included','fully inclusive workplace','100% inclusive','guaranteed equal opportunities','no pay gap','zero pay gap'],'Diversity, equality and inclusion claim','Medium','Absolute inclusion, equality or pay-gap wording may overstate outcomes unless backed by data, scope, baseline and progress evidence.','Add workforce data, baseline, scope, limitations, methodology and progress indicators.'),
 (_ASPIRATIONAL_SOCIAL_VERBS,'Aspirational or future social-performance claim','High','The wording describes an ambition or ongoing effort ("working towards", "wish to build a world where") rather than an achieved, current-state outcome. Research on fashion-sector sustainability communication (KU Leuven/HIVA, 2026) found this pattern -- vague, forward-looking commitments on wages, human rights or working conditions with no baseline, timeline or achieved result -- to be the dominant driver of social-washing risk, distinct from absolute assurance wording.','State what has actually been achieved to date and on what evidence basis, and give a specific timeline and measurable target for the remaining ambition. Do not present an ongoing effort as if it were a current outcome.'),
]





def calc_green_score(findings, sector, ext, page_text, audience):
    material=_material_findings(findings)
    substantiation, evidence_notes=green_evidence_signal_score(page_text, findings)
    external_context=green_external_context_risk(ext)
    external_score=external_context.get('score',0)
    sector_score=sector_environment_score(sector)
    audience_label=audience.get('audience','') if isinstance(audience,dict) else ''
    audience_factor=1.0 if ('Client-facing' in audience_label or 'Consumer-facing' in audience_label or 'commercial' in audience_label.lower()) else 0.90 if ('Mixed' in audience_label or 'unclear' in audience_label.lower()) else 0.75
    regulatory=any(f.get('blacklisted_practice_indicator') for f in material)
    score=_recalibrated_score(material, substantiation, evidence_notes, external_score, sector_score, regulatory, audience_factor)
    top=max([f.get('claim_score',0) for f in material] or [8])
    comps={'claim_wording_risk':min(100, top + 5*(len(material)-1)) if material else 8,'substantiation_risk':15 if not material else max(0,100-substantiation),'external_context_risk':external_score,'sector_baseline_risk':sector_score,'substantiation_score':substantiation,'evidence_notes':evidence_notes,'audience_factor':audience_factor,'score_calculation_note':'Score = 42% claim wording severity + 24% evidence gap + 22% external stakeholder context + 12% sector/channel sensitivity, weighted by audience factor and capped conservatively so that isolated claim signals cannot alone drive a High/Very high result unless they are a direct blacklisted-practice indicator or are supported by negative external stakeholder signals.'}
    return score, comps, external_context

def calc_score(findings,sector,context,external_research=None,page_text="",company_name=""):
    material=_material_findings(findings)
    substantiation, evidence_notes=evidence_signal_score(page_text, findings)
    external_context=strict_external_context_risk(external_research or {}, company_name)
    external_score=external_context.get('score',0)
    sector_score={"Low":10,"Medium":35,"High":60}.get(sector.get("level","Medium"),35)
    regulatory=any(('forced-labour' in f.get('type','').lower() or 'forced labor' in f.get('type','').lower()) for f in material)
    score=_recalibrated_score(material, substantiation, evidence_notes, external_score, sector_score, regulatory, 1.0)
    external_mod, external_note=external_relevance_score(findings, external_research or {})
    top=max([f.get('claim_score',0) for f in material] or [8])
    comps={"claim_wording_risk":min(100, top + 5*(len(material)-1)) if material else 8,"substantiation_risk":15 if not material else max(0,100-substantiation),"external_context_risk":external_score,"sector_baseline_risk":sector_score,"substantiation_score":substantiation,"evidence_notes":evidence_notes,"score_calculation_note":"Score = 42% claim wording severity + 24% evidence gap + 22% external stakeholder context + 12% sector/channel sensitivity, capped conservatively so that isolated claim signals cannot alone drive a High/Very high result unless they are a direct regulatory (forced-labour) indicator or are supported by negative external stakeholder signals."}
    return score, external_mod, external_note, evidence_quality_credit(page_text, findings), comps

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

class Handler(BaseHTTPRequestHandler):
    def _send(self,body,ctype="text/html; charset=utf-8",status=200,extra_headers=None):
        if isinstance(body,str): body=body.encode()
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type")
        for k,v in (extra_headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def _json(self,d,status=200): self._send(json.dumps(d,ensure_ascii=False,indent=2),"application/json; charset=utf-8",status)
    def _respond_pdf(self,scan_result):
        build_fn=_get_build_company_report_pdf()
        if build_fn is None:
            return self._json({"error":"PDF report generation is unavailable: "+(_report_pdf_import_error or "unknown import error")},500)
        try:
            pdf_bytes=build_fn(scan_result)
        except Exception as e:
            return self._json({"error":"Could not generate PDF report: "+str(e)},500)
        stamp=re.sub(r"[^0-9-]","",(scan_result.get("analysis_date") or datetime.date.today().isoformat())[:10])
        fname=f"durably_company_report_{stamp or datetime.date.today().isoformat()}.pdf"
        return self._send(pdf_bytes,"application/pdf",200,{"Content-Disposition":f'attachment; filename="{fname}"'})
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_OPTIONS(self): self._json({"ok":True})
    def do_GET(self):
        if self.path=="/" or self.path.startswith("/?"): self._send((APP_DIR/"frontend.html").read_text(encoding="utf-8"))
        elif self.path=="/methodology.pdf":
            pdf=APP_DIR/"methodology.pdf"
            if pdf.exists(): self._send(pdf.read_bytes(),"application/pdf")
            else: self._json({"error":"Methodology PDF not found"},404)
        elif self.path=="/api/health": self._json({"status":"ok","version":APP_VERSION,"tavily_configured":bool(TAVILY_API_KEY),"google_search_configured":bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX),"google_api_key_configured":bool(GOOGLE_SEARCH_API_KEY),"google_cx_configured":bool(GOOGLE_SEARCH_CX),"report_pdf_available":(_report_pdf_fn is not None or _report_pdf_import_error is None)})
        else: self._json({"error":"Not found"},404)
    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length",0)); data=json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if self.path=="/api/scan/url":
                u=data.get("url","")
                if not u: return self._json({"error":"No URL provided"},400)
                result=analyse_url(u)
                if data.get("format")=="pdf": return self._respond_pdf(result)
                return self._json(result)
            if self.path=="/api/scan/document":
                filename=data.get("filename","uploaded_document")
                content=data.get("content_base64","")
                if not content: return self._json({"error":"No document content provided"},400)
                txt=decode_uploaded_document(filename, content, data.get("mime_type",""))
                result=analyse_uploaded_document(filename, txt, data.get("company_name",""))
                if data.get("format")=="pdf": return self._respond_pdf(result)
                return self._json(result)
            if self.path=="/api/report/pdf":
                if not data:
                    return self._json({"error":"No scan result provided"},400)
                return self._respond_pdf(data)
            self._json({"error":"Unknown endpoint"},404)
        except Exception as e: self._json({"error":str(e)},500)

# V55 claim-signal sensitivity and report layout refinements

# The scan should retain enough claim signals to be useful, but only where wording is a real
# sustainability claim signal (not a neutral reference such as 'backing British suppliers').
V55_GREEN_EXTRA_PATTERNS = [
    ('Generic environmental claim', 'High', ['more sustainable','sustainable fashion','sustainable clothing','sustainable garment','sustainable garments','sustainable product','sustainable products','sustainable collection','sustainable range','sustainable choice','sustainable materials','sustainable cotton','sustainable viscose','sustainable fibres','sustainable fibers','sustainably sourced','responsibly sourced material','responsible materials','lower-impact material','low-impact material','eco-design','eco design','conscious collection','join life','preferred materials'],
     'EmpCo risk: broad environmental wording such as sustainable, eco, conscious, preferred or lower-impact can be misleading where the exact environmental attribute, scope and evidence are not clear on the same medium.',
     'Specify the exact attribute, product/material scope, baseline, method, evidence, reporting period and limitations.'),
    ('Recycled / recyclable material claim', 'Medium', ['recycled polyester','recycled cotton','recycled material','recycled materials','made from recycled','made with recycled','recyclable packaging','recycled packaging','recyclable materials','circular material','circular materials'],
     'Recycled, recyclable or circular-material wording can be a sustainability claim where conditions, percentage, certification, local recyclability or material scope are unclear.',
     'State the recycled content percentage, material scope, certification or chain-of-custody basis, and practical recyclability conditions.'),
    ('Generic environmental claim', 'High', ['environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','eco-friendly','climate friendly','green choice','eco choice','green product','eco product'],
     'EmpCo risk: generic environmental claims are high-sensitivity claims and may be prohibited if they are not specified clearly and prominently or backed by recognised excellent environmental performance.',
     'Replace generic wording with a specific, evidence-backed statement on the exact attribute and scope.'),
]

V55_SOCIAL_EXTRA_PATTERNS = [
    ('Supplier-responsibility / sourcing claim', 'High', ['responsible sourcing','responsibly sourced','ethical sourcing','ethically sourced','supplier code','supplier code of conduct','supplier standards','audited suppliers','certified suppliers','traceable suppliers','traceable supply chain','supply chain traceability','responsible supply chain','sustainable sourcing','all suppliers comply','all suppliers meet','supplier due diligence'],
     'Supplier and sourcing claims can imply control over supply-chain conduct, audit quality, traceability, due diligence or compliance. They require scope, coverage, methodology, limitations and remediation evidence.',
     'State supplier tiers covered, audit/assessment method, traceability limits, worker voice, corrective-action closure and remediation approach.'),
    ('Human-rights / labour-rights claim', 'High', ['human rights due diligence','respect human rights','protect human rights','labour rights','labor rights','worker rights','fair wages','living wage','decent work','no child labour','no child labor'],
     'Human-rights or labour-rights wording is a high-sensitivity social claim where due diligence, salient risks, grievance channels and remedy are not visible.',
     'Connect the claim to salient-risk assessment, governance, grievance channels, tracking and remedy.'),
    ('Forced-labour product or supply-chain claim', 'High', ['forced labour free','forced labor free','free from forced labour','free from forced labor','modern slavery free','no forced labour','no forced labor','forced-labour due diligence','forced labor due diligence'],
     'Forced-labour or modern-slavery assurance wording can create a product/supply-chain compliance impression under the EU Forced Labour Regulation lens.',
     'Scope the claim and document product/supplier traceability, forced-labour risk assessment, mitigation, remediation and withdrawal/customs response readiness.'),
    ('Broad social-impact claim', 'Medium', ['positive social impact','positive impact on communities','support communities','supporting communities','empowering communities','inclusive growth'],
     'Broad community or social-impact wording can overstate outcomes where stakeholders, geography, metrics and limitations are not defined.',
     'Specify stakeholder group, geography, objective, indicators, period, evidence and limitations.'),
]

V55_NAV_CONTEXT_EXCLUSIONS = [
    'cookie', 'privacy', 'terms', 'login', 'sign in', 'menu', 'navigation', 'subscribe', 'newsletter',
    'download report', 'annual report', 'sustainability report', 'press release archive',
    'read more about', 'learn more about', 'find out more about', 'more about our',
    'explore our', 'discover our', 'read on to', 'click here', 'see more'
]

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
        if cap_starts/len(words) > 0.5 and not re.search(r'\b(we|our|is|are|has|have|will|to)\b', c.lower()):
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

def _v55_claim_context_ok(excerpt, trigger, dimension):
    c=(excerpt or '').lower(); trig=(trigger or '').lower()
    if len(c.strip()) < 25:
        return False
    if _looks_like_toc_or_index(excerpt):
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
    # Exclude headings that have no claim object.
    if len(c.split()) <= 5 and not any(x in c for x in ['product','packaging','material','supplier','sourcing','rights','wage','community','recycled','recyclable','net zero','carbon']):
        return False
    if 'challenges' in c and 'opportunities' in c:
        return False
    # v57m: statements that describe what a law/regulation/SDG requires, or what "living wage",
    # "fair wages" or "decent work" mean in general (citations, statistics, definitions,
    # references to an SDG or ILO convention) are not first-person company claims, even when
    # they happen to contain "we"/"our" only in an industry-wide or advocacy sense.
    definitional_citation=['according to the','research shows','research suggests','studies show','study shows',
        'data shows','is estimated at','is defined as','refers to','supports un sustainable development goal',
        'sustainable development goal','sdg 8','ilo convention','csddd requires','csrd requires','the law requires',
        'regulation requires','directive requires','is a fundamental part of']
    if any(n in c for n in definitional_citation) and not any(x in c for x in ['we ensure','we guarantee','we comply','we are compliant','our compliance','we achieve','we have achieved']):
        return False
    if 'our industry' in c and not any(x in c for x in ['we ensure','we guarantee','we comply','our operations','our supply chain','our products','our business']):
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
    has_first_person=bool(re.search(r'\b(we|our|us)\b', c))
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
                        'according to','standard','iso','sa8000','third-party','independent','kpi','baseline','policy']
    has_specific=any(x in c for x in specificity_terms) or bool(re.search(r'\b\d{1,3}(?:[.,]\d+)?\s?%\b', c))
    if t.startswith('no ') or t.startswith('no material'):
        return {'status':'Not applicable','comment':'No material social claim was detected.'}
    if has_specific:
        return {'status':'Partly specified','comment':'Some substantiation indicators (e.g. audit, certification, scope, %) were found, but coverage, methodology and remediation should still be verified.'}
    if any(x in t for x in ['forced','modern slavery','supply','supplier','human rights','labour','labor']):
        return {'status':'Likely insufficient','comment':'The detected wording implies assurance or coverage but the retained passage shows no visible scope, audit basis, methodology or remediation evidence.'}
    return {'status':'Needs review','comment':'The claim should be checked for precise scope, evidence and remediation basis.'}

def social_blacklisted_indicator(claim_type, trigger, claim_text):
    t=(claim_type or '').lower(); trig=(trigger or '').lower()
    if 'forced' in t or 'modern slavery' in t:
        return ('Forced Labour Regulation readiness & substantiation flag (Regulation (EU) 2024/3015; core provisions apply from 14 December 2027): wording implying products, suppliers or the '
                'supply chain are free from forced labour requires traceability, risk assessment, mitigation and remediation evidence ahead of that date; it cannot rest on a policy statement '
                'alone. This is a readiness/substantiation signal, not a finding that the Regulation has been breached.')
    if 'supply' in t or 'supplier' in t:
        return 'Potential red flag if supplier-coverage or audit wording (e.g. "all suppliers", "audited", "certified") is not backed by disclosed tier coverage, audit methodology and corrective-action closure rates.'
    if 'human rights' in t or 'labour' in t or 'labor' in t:
        return 'Potentially misleading social claim if human-rights/labour wording is not backed by a disclosed due-diligence process, grievance mechanism and remedy evidence. Social characteristics fall under EmpCo Art. 6(1)(b) but, unlike specific environmental Annex I practices, are assessed case-by-case rather than via a fixed blacklist.'
    return 'No direct regulatory-blacklist indicator identified, but claim-specific substantiation is still required.'

def enrich_social_finding(f, trigger=''):
    f['regulatory_signal']=social_blacklisted_indicator(f.get('type',''), trigger, f.get('claim',''))
    f['specification_check']=social_specification_check(f.get('type',''), f.get('claim',''))
    f['pre_publication_decision']='Do not publish/reuse without legal/compliance and evidence review.' if f.get('risk')=='High' and not f.get('type','').lower().startswith('no ') else 'Can normally proceed only after standard evidence and wording review.'
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
    low=(text or '').lower(); fs=[]; seen=set()
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
    fs=sorted(fs,key=lambda f:f.get('claim_score',0), reverse=True)[:12]
    if not fs:
        fs.append(enrich_green_finding({'dimension':'green','type':'No material problematic green claim retained','risk':'Low','claim':'No exact problematic green claim was retained from the reviewed material.','issue':'The scan did not retain a direct EmpCo blacklisted-practice indicator or high-sensitivity environmental claim. General sustainability context is not scored as a problematic claim unless it contains specific claim wording.','rewrite':'No rewrite is needed unless the company wants to make a specific environmental claim.','claim_score':8,'standards':['General green-claim quality review'],'action':'Keep environmental claims specific, scoped and evidence-backed.','problematic_terms':[]},''))
    return fs

def detect_claims(text):
    low=(text or '').lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        hits=0
        for trig in triggers:
            if _trigger_present(trig, low):
                excerpt=_v55_sentence_list(text,trig)
                if not _social_claim_context(excerpt, typ, trig):
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
    raw=round((claim_wording*0.42 + evidence_gap*0.24 + external_score*0.22 + sector_score*0.12)*audience_factor)
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

def main():
    print(f"Sustainability Scan {APP_VERSION}"); print(f"Serving on http://{HOST}:{PORT}"); print("Tavily configured:",bool(TAVILY_API_KEY)); print("Google Search configured:",bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)); HTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()