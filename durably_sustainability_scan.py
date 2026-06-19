#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime, base64, zipfile, re, io

APP_VERSION="hostable_v53_scan_timeout_resilience"
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
CLAIMS=[
 (["positive impact","social impact","people first","support society","better for everyone","social value","community impact"],"Broad social-impact claim","Medium","The wording suggests positive social outcomes but does not clearly define scope, affected stakeholders, metrics, outcomes or limitations.","Use scoped wording linked to measurable outcomes, for example: 'We track access to services for identified customer groups and report annual progress against defined inclusion indicators.'"),
 (["ethical","fair","responsible","trusted","socially responsible","caring","worker-friendly"],"Broad ethical or responsible-business claim","High","The wording reassures users about responsible conduct, but may not specify criteria, scope, exclusions, verification method or evidence.","Replace broad wording with evidence-based language, for example: 'We apply defined responsible-sourcing criteria to selected high-risk categories and disclose audit coverage and corrective-action progress.'"),
 (["human rights","labour rights","labor rights","decent work","forced labour","forced labor","child labour","child labor","living wage","modern slavery"],"Human-rights or labour-rights claim","High","The claim refers to sensitive rights topics but may not show due diligence, salient risks, grievance channels, tracking or remedy.","State the process and limits, for example: 'We assess selected human-rights risks in priority supply chains and report actions, grievance channels and remediation progress.'"),
 (["forced labour free","forced labor free","free from forced labour","free from forced labor","no forced labour","no forced labor","modern slavery free","forced labour due diligence","forced labor due diligence","product traceability","import controls","supplier traceability"],"Forced-labour product or supply-chain claim","High","EU Forced Labour Regulation risk: the wording may imply that products, imports, exports or supply chains are free from forced labour. Such claims require robust product/supplier traceability, forced-labour risk assessment, mitigation, remediation and response procedures.","Scope the wording, for example: 'We apply a risk-based forced-labour due-diligence process to selected higher-risk products and suppliers, with traceability, escalation and remediation steps disclosed.'"),
  (["supply chain","value chain","all suppliers","responsible sourcing","ethical sourcing","supplier code","supplier standards","supplier due diligence","supplier audit","supplier audits","audited suppliers","certified suppliers","traceable suppliers","supplier traceability","human rights in the supply chain","supply-chain transparency"],"Supply-chain or supplier-responsibility claim","High","The wording may imply responsible value-chain control, supplier coverage, traceability, audit quality or remediation. A neutral reference to suppliers, such as supporting local suppliers, is not treated as a high-risk social claim unless it is linked to responsible-sourcing, traceability, human-rights, audit, certification or absolute coverage language.","Scope the claim, for example: 'We assess higher-risk suppliers through a risk-based process and disclose supplier coverage, key findings and corrective-action closure rates.'"),
 (["diversity","inclusion","inclusive","equality","equal opportunities","pay equity","gender equality","non-discrimination"],"Diversity, equality and inclusion claim","Medium","The claim refers to inclusion or equality but may not provide workforce data, baseline, targets, pay-equity information or progress evidence.","Add measurable evidence, for example: 'We monitor diversity and inclusion through workforce data, employee feedback and targeted action plans, with progress reported annually.'"),
 (["safe workplace","safe working","health and safety","well-being","wellbeing","worker welfare","quality of life","care for employees"],"Health, safety or worker-welfare claim","High","The claim suggests safe or positive working conditions but may not provide incident data, contractor coverage, workload evidence, worker feedback or remedy.","Link to controls and outcomes, for example: 'We monitor health and safety through incident reporting, training, contractor coverage and corrective actions.'"),
 (["accessibility","vulnerable customers","customer care","fair treatment","customer protection","affordable for all","financial inclusion","digital inclusion"],"Customer welfare or accessibility claim","Medium","The claim concerns customer welfare or inclusion but may not show measurable access, complaints, remedy or vulnerable-customer safeguards.","Add evidence, for example: 'We track accessibility and customer inclusion through service metrics, complaint handling and improvement actions for vulnerable groups.'"),
 (["everyone","all employees","all workers","all suppliers","for all","highest","best","fully","guarantee","zero","always","never","100%"],"Absolute or broad wording","High","Absolute terms may overstate coverage, control or outcomes and create a high evidence burden.","Qualify the wording, for example: replace 'all suppliers meet our highest standards' with 'selected higher-risk suppliers are assessed against our supplier code, with limitations and corrective actions disclosed.'")
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
 {"name":"CSRD / ESRS S1-S4","use":"Connect social claims to policies, actions, targets, metrics and affected stakeholder groups: own workforce, value-chain workers, affected communities, consumers and end-users."},
 {"name":"CSDDD","use":"Support human-rights and supply-chain claims with risk-based due diligence, prevention, mitigation, tracking and remediation."},
 {"name":"EU Forced Labour Regulation — Regulation (EU) 2024/3015","use":"Check product, supplier and import/export claims against the EU prohibition on placing, making available on the Union market, or exporting products made with forced labour. Evidence should cover forced-labour risk assessment, supplier/product traceability, preventive actions, remediation and withdrawal/response readiness."},
 {"name":"OECD Guidelines","use":"Check whether responsible-business claims are backed by identification, prevention, mitigation and accounting for adverse impacts."},
 {"name":"UN Guiding Principles on Business and Human Rights","use":"Support human-rights claims with policy commitment, due diligence, grievance channels and remedy."},
 {"name":"UN Global Compact","use":"Check consistency with principles on human rights, labour, environment and anti-corruption when responsible-business conduct is invoked."},
 {"name":"ILO Fundamental Principles and Rights at Work","use":"Check worker and supplier claims against freedom of association, collective bargaining, forced labour, child labour, non-discrimination and safe work."},
 {"name":"GRI Standards","use":"Check whether claims are balanced, evidence-based and supported by impacts, management approach, indicators and corrective actions."}
]
def standards_for_claim(t):
    x=(t or "").lower()
    if "forced" in x or "modern slavery" in x: return ["EU Forced Labour Regulation 2024/3015","CSRD/ESRS S2","CSDDD","OECD Guidelines","UNGPs","ILO","UNGC"]
    if "human" in x or "labour" in x or "labor" in x: return ["CSRD/ESRS S1-S2","CSDDD","EU Forced Labour Regulation 2024/3015","OECD Guidelines","UNGPs","ILO","UNGC"]
    if "supply" in x or "supplier" in x: return ["CSRD/ESRS S2","CSDDD","OECD Guidelines","UNGPs","ILO"]
    if "diversity" in x or "inclusion" in x: return ["CSRD/ESRS S1","ILO","GRI","UNGC"]
    if "customer" in x or "accessibility" in x: return ["CSRD/ESRS S4","OECD Guidelines","GRI"]
    if "worker" in x or "safety" in x: return ["CSRD/ESRS S1","ILO","GRI"]
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
def compact_sources(results,limit=6):
    out=[]
    for r in results[:limit]:
        txt=(r.get("title","")+" "+r.get("url","")+" "+r.get("content","")).lower()
        cat="Public web"
        if any(v in txt for v in ["ngo","amnesty","oxfam","human rights watch","clean clothes"]): cat="NGO / civil society"
        elif any(v in txt for v in ["gov","europa","regulator","authority","commission","oecd","ncp"]): cat="Government / regulator"
        elif any(v in txt for v in ["lawsuit","court","legal","complaint"]): cat="Legal / complaint"
        elif any(v in txt for v in ["reuters","ft.com","bbc","guardian","press"]): cat="Press"
        out.append({"title":r.get("title","")[:150],"url":r.get("url",""),"content":r.get("content","")[:220],"category":cat,"credibility":source_credibility(r),"provider":r.get("provider","")})
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

def crawl_with_related_sites(original_url):
    """Crawl the requested URL plus a small number of likely related company sites.
    The requested URL remains the primary source. Related domains are added only when reachable.
    """
    txt,pages=crawl(original_url)
    source_notes=[]
    all_text=[txt]
    all_pages=list(pages)
    for candidate in related_company_sites(original_url):
        try:
            rt,rpages=crawl(candidate)
            if len(rt)>500:
                all_text.append('\n\nRELATED COMPANY SITE: '+candidate+'\n'+rt)
                all_pages.extend([p for p in rpages if p not in all_pages])
                source_notes.append(f"Related company site also checked: {candidate}")
        except Exception:
            pass
    return '\n\n'.join(all_text)[:140000], all_pages[:12], source_notes

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
def fetch_html(url):
    p=urlparse(url)
    if p.scheme not in ("http","https") or not p.hostname: raise ValueError("Invalid URL.")
    if is_private(p.hostname): raise ValueError("Private/local URLs are blocked.")
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 GreenSocialClaimsAssessment/40.0","Accept":"text/html,application/xhtml+xml"})
    with urlopen(req,timeout=7,context=ssl.create_default_context()) as r:
        if "html" not in r.headers.get("content-type","").lower(): raise ValueError("URL does not return an HTML page.")
        return r.read(2000000).decode("utf-8",errors="ignore")
def same_domain(u,base):
    h=urlparse(u).hostname or ""
    return h==base or h.endswith("."+base)
def relevant(h):
    h=h.lower()
    return any(k in h for k in ["sustain","responsib","people","human","rights","divers","inclusion","supplier","ethic","impact","community","accessibility","safety","annual","report","esg","environment","climate","circular","green","sourcing","governance","modern-slavery","modern_slavery","non-financial","investor"])
def crawl(url):
    html=fetch_html(url); text,links=parse_html(html); host=urlparse(url).hostname or ""
    pages=[url]; chunks=[text]; cands=[]
    for href in links:
        full=urljoin(url,href).split("#")[0]
        if same_domain(full,host) and relevant(full) and full not in cands and full!=url: cands.append(full)
    for link in cands[:3]:
        try:
            t,_=parse_html(fetch_html(link))
            if len(t)>200: chunks.append("\n\nPAGE: "+link+"\n"+t); pages.append(link)
        except Exception: pass
    return "\n\n".join(chunks)[:90000], pages
def infer_company(url,text):
    combo=(url+" "+text[:5000]).lower()
    for k,p in PROFILES.items():
        if k in combo: return {"company":p[0],"sector":p[1],"sector_risk":p[2],"context":p[3]}
    host=urlparse(url).hostname or ""; name=host.replace("www.","").split(".")[0].title()
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
    return [{"title":i.get("title",""),"url":i.get("url",""),"content":i.get("content",""),"score":i.get("score",0)} for i in data.get("results",[])]

def google_search(query, max_results=5):
    """Google Custom Search JSON API fallback. Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return []
    from urllib.parse import urlencode
    params=urlencode({"key":GOOGLE_SEARCH_API_KEY,"cx":GOOGLE_SEARCH_CX,"q":query,"num":max(1,min(max_results,10))})
    req=Request("https://www.googleapis.com/customsearch/v1?"+params,headers={"User-Agent":"Mozilla/5.0 GreenSocialClaimsAssessment/40.0"},method="GET")
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

def detect_claims(text):
    low=text.lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        trig=_find_valid_trigger(text,triggers,typ)
        if trig and typ not in seen:
            seen.add(typ); score=72 if typ=="Forced-labour product or supply-chain claim" else (56 if risk=="High" else 32)
            claim_excerpt=snip(text,trig)
            fs.append({"type":typ,"risk":risk,"claim":claim_excerpt,"issue":issue,"rewrite":rewrite,"claim_score":score,"standards":standards_for_claim(typ),"action":("Document product/supplier traceability, forced-labour risk assessment, mitigation, remediation and withdrawal/customs response readiness." if typ=="Forced-labour product or supply-chain claim" else "Substantiate the claim with scope, evidence, reporting period, limitations and remediation steps."),"problematic_terms":problematic_terms_for_finding(claim_excerpt,typ)})
    if not fs: fs.append({"type":"No major high-risk social claim detected","risk":"Low","claim":text[:320]+("..." if len(text)>320 else ""),"issue":"The crawler did not detect obvious high-risk social-claim wording in the reviewed company pages.","rewrite":"Keep social claims specific, scoped and supported by measurable evidence.","claim_score":18,"standards":["General claim-quality review"],"action":"Keep the claim specific, scoped and supported by measurable evidence.","problematic_terms":[]})
    return sorted(fs,key=lambda f:f["claim_score"],reverse=True)
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
        return "Potential social-washing concern — evidence review needed"
    if external_score >= 40 and evidence_gap >= 55:
        return "High social-washing risk signal — verify urgently"
    return "Potential social-washing concern — not enough contradiction evidence for High"

def calc_score(findings,sector,context,external_research=None,page_text=""):
    """
    V25 social-washing assessment scoring:
    - 30% claim wording risk
    - 30% substantiation / evidence-gap risk
    - 25% external contradictory-context risk
    - 15% sector sensitivity
    High risk requires: sensitive/broad claim + evidence gap + relevant external contradiction.
    Sector sensitivity cannot by itself create a High result.
    """
    claim=max(f.get("claim_score",0) for f in findings)
    high_claims=len([f for f in findings if f.get("risk")=="High"])
    no_major=findings and findings[0].get("type","").lower().startswith("no major")
    claim_wording=min(100,round(claim*1.25)) if not no_major else 15
    substantiation, evidence_notes=evidence_signal_score(page_text, findings)
    evidence_gap=25 if no_major else max(0,100-substantiation)
    external_context=strict_external_context_risk(external_research or {}, "")
    external_score=external_context.get("score",0)
    sector_score={"Low":10,"Medium":35,"High":60}.get(sector.get("level","Medium"),35)
    raw=round(claim_wording*0.30 + evidence_gap*0.30 + external_score*0.25 + sector_score*0.15)
    external_mod, external_note = external_relevance_score(findings, external_research or {})
    # Conservative caps aligned with social-washing definition.
    if no_major:
        raw=min(raw,28 if external_score < 40 else 38)
    if high_claims==0:
        raw=min(raw,49)
    if evidence_gap < 45:
        raw=min(raw,49)
    if external_score < 40:
        raw=min(raw,59)
    if raw >= 80 and not (high_claims>=2 and evidence_gap>=70 and external_score>=65 and sector.get("level")=="High"):
        raw=min(raw,74)
    raw=max(0,min(100,raw))
    return raw, external_mod, external_note, evidence_quality_credit(page_text, findings), {"claim_wording_risk":claim_wording,"substantiation_risk":evidence_gap,"external_context_risk":external_score,"sector_baseline_risk":sector_score,"substantiation_score":substantiation,"evidence_notes":evidence_notes}

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
    return [{"claim_text":f.get("claim",""),"claim_type":f.get("type",""),"risk_level":f.get("risk",""),"claim_score":f.get("claim_score",0),"risk_reason":f.get("issue",""),"evidence_needed":evidence_checklist(f),"suggested_rewrite":f.get("rewrite",""),"standards":f.get("standards",[])} for f in findings]

def build_red_flags(findings,ext,sector,context):
    flags=[]
    if any(f.get("risk")=="High" for f in findings): flags.append("Broad or high-sensitivity social claims appear on the website and may require stronger substantiation.")
    if any(("supplier" in f.get("type","").lower() or "supply" in f.get("type","").lower()) for f in findings): flags.append("Supply-chain wording should be checked against supplier coverage, audit quality, worker voice and remediation evidence.")
    if any(("forced" in f.get("type","").lower() or "modern slavery" in f.get("type","").lower()) for f in findings): flags.append("Potential EU Forced Labour Regulation red flag: forced-labour or modern-slavery wording should not imply product/supply-chain assurance unless product/supplier traceability, risk assessment, remediation and withdrawal/customs response readiness are evidenced.")
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
            flags.append('Potential EmpCo red flag: a high-sensitivity consumer-facing green claim appears to require stronger substantiation, clearer scope or safer wording before external use.')
            break
    for f in social_findings or []:
        typ=(f.get('type','')+' '+f.get('issue','')+' '+f.get('claim','')).lower()
        if f.get('risk')=='High' and any(t in typ for t in ['forced labour','forced labor','modern slavery','product traceability','import controls','supplier traceability']):
            flags.append('Potential EU Forced Labour Regulation red flag: forced-labour, modern-slavery, traceability or product/supplier assurance wording should be escalated for legal/compliance review.')
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

def build_confidence(pages,ext,findings):
    pts=0; reasons=[]
    if len(pages)>=3: pts+=2; reasons.append("several company pages were reviewed")
    elif len(pages)>=1: pts+=1; reasons.append("at least the main company page was reviewed")
    if ext.get("enabled") and len(ext.get("results",[]))>=5: pts+=2; reasons.append("external public-source search returned several results")
    elif ext.get("enabled"): pts+=1; reasons.append("external public-source search was active")
    else: reasons.append("external public-source search was not active")
    if findings and not findings[0].get("type","").lower().startswith("no major"): pts+=1; reasons.append("claim-level signals were detected")
    return {"level":"High" if pts>=5 else "Medium" if pts>=3 else "Low","reasons":reasons}

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
            "analysis": specific_claim_analysis(f, company, sector) if "specific_claim_analysis" in globals() else (f.get("issue","") + " " + f.get("action","")).strip(),
            "evidence_needed": evidence_checklist(f) if "evidence_checklist" in globals() else [],
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

def is_negative_external_source(result):
    text = _external_signal_text(result)
    hard_negative = any(t in text for t in [
        "greenwashing","social washing","misleading","accused","accusation","allegation","criticised","criticized",
        "complaint","lawsuit","court","investigation","fine","penalty","sanction","regulator","authority",
        "watchdog","union","strike","protest","boycott","violation","breach","forced labour","forced labor",
        "child labour","child labor","modern slavery","human rights abuse","unsafe","discrimination","settlement"
    ])
    stakeholder_context = any(t in text for t in ["ngo","union","court","regulator","authority","watchdog","media","press","reuters","guardian","bbc","ft.com","oecd","ncp","complaint","lawsuit","investigation"])
    own_or_neutral = any(t in text for t in OWNED_OR_NEUTRAL_DOC_TERMS) and not hard_negative
    positive_only = any(t in text for t in POSITIVE_NOISE_TERMS) and not hard_negative
    return hard_negative and stakeholder_context and not own_or_neutral and not positive_only
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

def analyse_url(raw):
    original_url=norm_url(raw)
    fallback_note=""
    try:
        txt,pages,related_notes=crawl_with_related_sites(original_url)
        url=original_url
    except Exception as first_error:
        fallback_url=replace_tld_with_be(original_url)
        if fallback_url:
            try:
                txt,pages,related_notes=crawl_with_related_sites(fallback_url)
                url=fallback_url
                fallback_note=f"The original .com website was not accessible. The scan was automatically performed on {fallback_url}."
            except Exception as second_error:
                raise ValueError(f"The .com website could not be accessed and the .be fallback also failed. Original error: {first_error}. Fallback error: {second_error}.")
        else:
            raise first_error
    comp=infer_company(url,txt)
    fs=detect_claims(txt)
    ext=external(comp["company"], fs)
    exttext=" ".join(r.get("title","")+" "+r.get("content","") for r in ext.get("results",[]))
    sec=infer_sector(comp,txt+"\n"+exttext)
    ctx=infer_context(comp,txt,ext)
    score, external_modifier, external_modifier_note, evidence_credit, score_components = calc_score(fs,sec,ctx,ext,txt)
    external_context_v17 = strict_external_context_risk(ext, comp.get("company",""))
    # Use the stricter company-aware external context in the components.
    score_components["external_context_risk"] = external_context_v17.get("score", score_components.get("external_context_risk",0))
    splits = split_scores(fs,sec,ctx,external_modifier,score_components)
    conclusion = washing_conclusion(score, fs, splits.get("substantiation_risk",50), splits.get("external_context_risk",0))
    targeted = targeted_negative_sources(ext.get("results",[]), comp.get("company",""), 5)
    return {
        "version":APP_VERSION,
        "source_label":url,
        "original_url":original_url,
        "fallback_note":fallback_note,
        "analysis_date":datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "overall_score":score,
        "overall_risk":level(score),
        "screening_conclusion":conclusion,
        "methodology":"Social Washing Risk Assessment: claim + evidence gap + relevant contradictory context. Sector sensitivity is a modifier, not a standalone risk trigger.",
        "company":comp,
        "sector":sec,
        "context":ctx,
        "findings":fs,
        "report":build_report(comp,sec,ctx,fs,score,pages),
        "assessment_summary_specific":reader_friendly_summary(comp,sec,fs,ext,score,score_components),
        "concise_standards_lens":concise_standards_lens(),
        "merged_claims":merge_claim_sections(fs, comp, sec),
        "external_research":dict(ext, compact_sources=targeted, targeted_negative_sources=targeted),
        "external_context_assessment":external_context_v17,
        "external_modifier":external_modifier,
        "external_modifier_note":external_modifier_note,
        "evidence_credit":evidence_credit,
        "score_components":score_components,
        "split_scores":splits,
        "integrated_score":integrated_score_view(score, splits, external_context_v17),
        "why_score":structured_why_score(comp,sec,ctx,fs,external_context_v17,splits,score_components),
        "claim_inventory":build_claim_inventory(fs),
        "stakeholder_red_flags":build_red_flags(fs,ext,sec,ctx),
        "company_action_plan":build_company_action_plan(fs,sec,ext),
        "engagement_questions":build_engagement_questions(fs,ext),
        "confidence":build_confidence(pages,ext,fs),
        "disclaimer":"Indicative first-pass social-washing assessment only. It is not legal advice and not a finding that social washing occurred. External search results are review signals that require verification.",
        "analysed_text_excerpt":txt[:2200],
        "quality_improvements":["Use claim-specific wording rather than broad reassurance language.","Connect each claim to scope, metrics, reporting period and limitations.","For supplier, human-rights or worker claims, add due-diligence, grievance and remediation evidence.","Check whether external public-source signals contradict or qualify the claim."],
        "ai_used":False,
        "ai_note":""
    }



# -----------------------------
# V27 GREEN + SOCIAL CLAIMS EXTENSION
# -----------------------------
# Green-claims module based on Directive (EU) 2024/825 (EmpCo), which amends the UCPD.
# The directive is primarily a B2C/commercial-communication consumer-protection framework.
# This scanner therefore distinguishes consumer-facing pages from investor/internal reports.

GREEN_CLAIMS=[
 # EmpCo / UCPD blacklisted or high-sensitivity claim categories derived from the Agoria/ICC Belgium greenwashing event.
 (['sustainable','green','eco-friendly','environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','ecological','eco','biobased','bio-based','climate friendly','climate-friendly'],'Generic environmental claim','High','EmpCo risk: generic environmental claims need clear and prominent specification on the same medium or recognised excellent environmental performance relevant to the claim as a whole. Vague wording can become a blacklisted-practice indicator in consumer-facing communication.','Replace generic wording with specific, evidenced wording, e.g. “This packaging contains X% recycled cardboard, verified under [scheme], for [market/period].”'),
 (['carbon neutral','climate neutral','co2 neutral','co₂ neutral','net zero product','carbon negative','carbon positive','climate positive','carbon compensated','climate compensated','offset','offsetting','compensated emissions','reduced climate impact'],'Climate-neutrality or offsetting claim','High','EmpCo risk: product-level claims that state or imply neutral, reduced or positive climate impact on the basis of greenhouse-gas offsetting are a high-priority blacklisted-practice indicator. Company-level transition claims also require strict separation between real reductions and offsets.','Avoid product-level neutrality wording based on offsets. Separate actual emissions reductions from offsets; disclose scopes, baseline, methodology, residual emissions, offset role and progress.'),
 (['recyclable','recycled','recycled content','made from recycled','circular','circularity','closed loop','reuse','reusable','repairable','repairability','durable','durability','biodegradable','compostable'],'Circularity / durability / recyclability claim','Medium','EmpCo risk: environmental and circularity claims can mislead when they omit conditions, product coverage, local infrastructure, durability limits, repair availability or verification.','Specify the product parts, percentage, conditions, geography, testing standard, repair availability and limitations.'),
 (['less harmful','lower impact','reduced impact','lower emissions','reduced emissions','less co2','less co₂','lower carbon','energy efficient','water efficient','greener than','more sustainable than','better than','best environmental','lowest emissions'],'Comparative environmental claim','High','EmpCo risk: environmental or social comparisons must be accompanied by information on the comparison method, products and suppliers compared, data sources and measures to keep information up to date.','State the comparator, baseline, methodology, date, scope, data source and update mechanism; avoid vague “better/lower impact” claims.'),
 (['certified','label','eco label','ecolabel','sustainability label','verified','independently verified','approved by','green choice','eco choice','planet approved','green certified','responsible choice'],'Sustainability label / certification claim','High','EmpCo risk: self-declared sustainability labels are a blacklisted-practice indicator unless based on a public-authority label or an independent, transparent certification scheme. Icons, symbols, badges and trust marks can fall within this category.','Name the certification scheme, standard owner, scope, audit/verification basis, independence, transparency conditions and validity period.'),
 (['we will be net zero','we aim to be net zero','we are working towards net zero','by 2030','by 2040','by 2050','future environmental performance','transition plan','science based target','sbt','sustainable future','climate ambition','climate roadmap'],'Future environmental-performance claim','High','EmpCo risk: future environmental-performance claims require clear, objective, publicly available and verifiable commitments supported by a realistic implementation plan with measurable and time-bound targets.','Add a public implementation plan, milestones, resources, governance, progress indicators, independent verification and scope limitations.'),
 (['all natural','natural','clean','non-toxic','chemical free','zero impact','no impact','100% sustainable','fully sustainable','always sustainable','zero waste','waste free','pollution free'],'Absolute or purity environmental wording','High','EmpCo risk: absolute or purity wording may create an overbroad impression and carries a high evidence burden.','Qualify the claim; specify exact attribute, scope, test method, limitations and evidence.'),
 (['compliant with environmental law','meets legal requirements','according to legal standards','required by law','legal requirement','eu compliant','regulation compliant'],'Legal requirement presented as green benefit','High','EmpCo risk: presenting requirements imposed by law as a distinctive environmental feature of the product, service or trader is a blacklisted-practice indicator.','Do not present legal compliance as a differentiating sustainability benefit. Explain legal compliance separately from voluntary improvement claims.'),
 (['green leaf','leaf icon','tree icon','water drop','waterdrop','planet icon','earth icon','eco badge','green badge','environmental icon'],'Visual green-claim indicator','Medium','EmpCo risk: pictorial, graphic or symbolic representations can imply environmental benefits even without explicit text. Visual signals should be assessed like written claims.','Check whether the icon/badge implies a specific environmental benefit and connect it to clear, prominent and evidence-backed wording.'),
]


EMPCO_LENS=[
 {'name':'Directive (EU) 2024/825 / EmpCo','use':'Frames green-claim risk in B2C commercial communications by addressing misleading environmental claims, generic claims, labels, comparisons, durability/repairability and future environmental performance claims.'},
 {'name':'UCPD environmental-claim definition','use':'Checks whether text, images, symbols, labels, brand names, trade names or presentation imply positive, zero, reduced, comparative or improved environmental impact of a product, brand or trader.'},
 {'name':'Blacklisted-practices lens','use':'Flags high-sensitivity indicators such as generic environmental claims without clear specification or recognised excellent performance, self-declared sustainability labels, offset-based product neutrality claims, global claims based on one feature, and legal requirements presented as distinctive benefits.'},
 {'name':'Same-medium specification check','use':'Checks whether broad wording is specified clearly and prominently on the same page, advertisement, packaging text or product interface.'},
 {'name':'Climate / offsetting claims','use':'Separates actual emission reductions from offsetting or compensation and treats product-level neutrality wording based on offsets as a high-priority risk area.'},
 {'name':'Sustainability labels and visual claims','use':'Checks icons, badges, symbols and labels against independent certification, public-authority schemes, transparent criteria and validity.'},
 {'name':'Future environmental performance','use':'Future claims should be supported by clear, objective, publicly verifiable commitments, implementation plans, milestones, resources, governance and independent review.'},
 {'name':'Comparative environmental claims','use':'Checks whether comparisons disclose the comparison method, products/suppliers compared, data date, scope and update mechanism.'},
 {'name':'Consumer-facing communications','use':'EmpCo has strongest relevance for B2C/commercial communications; investor and internal documents remain relevant as evidence or consistency sources but are not treated the same as consumer marketing material.'}
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
        if txt:
            probe=' '.join(txt.split()[:10])
            for seg in page_segments or []:
                hay=(seg.get('text') or '').lower()
                if probe and probe in hay:
                    best=seg.get('url'); break
        if not best and page_segments:
            best=page_segments[0].get('url')
        if best:
            c['source_url']=best
            c['source_label']=page_name_from_url(best)
            d=docs_by_url.get(best,{})
            c['audience_group']=d.get('audience_group','mixed')
            c['audience_lens']=d.get('audience_assessment','Mixed or unclear')
            c['source_interpretation']=d.get('interpretation','')
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
            green.append(f.get('regulatory_signal','Potential EmpCo red flag.'))
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
    if 'climate-neutrality' in t or 'offset' in t:
        return 'High-priority EmpCo blacklisted-practice indicator where product-level neutral/reduced/positive climate impact is based on offsetting.'
    if 'label' in t or 'certification' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the label/badge is self-declared and not based on an independent certification scheme or public authority.'
    if 'generic environmental' in t:
        return 'Potential EmpCo blacklisted-practice indicator if the generic claim is not clearly specified on the same medium and not backed by recognised excellent environmental performance.'
    if 'legal requirement' in t:
        return 'EmpCo blacklisted-practice indicator if legal compliance is presented as a distinctive environmental benefit.'
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

def detect_green_claims(text):
    low=(text or '').lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in GREEN_CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            seen.add(typ)
            # High-sensitivity EmpCo categories receive a stronger claim-wording signal.
            if risk=='High':
                score=78 if any(x in typ.lower() for x in ['climate','label','generic','legal requirement']) else 70
            else:
                score=42
            claim_excerpt=snip(text,trig)
            f={'dimension':'green','type':typ,'risk':risk,'claim':claim_excerpt,'issue':issue,'rewrite':rewrite,'claim_score':score,'standards':['EmpCo / Directive (EU) 2024/825','UCPD misleading commercial practices'],'action':'Substantiate the green claim with scope, objective evidence, methodology, limits, same-medium specification and verification.','problematic_terms':problematic_terms_for_finding(claim_excerpt,typ)}
            fs.append(enrich_green_finding(f,trig))
    if not fs:
        f={'dimension':'green','type':'No major high-risk green claim detected','risk':'Low','claim':(text or '')[:320]+('...' if len(text or '')>320 else ''),'issue':'The crawler did not detect obvious high-risk green-claim wording in the reviewed pages.','rewrite':'Keep environmental claims specific, scoped and supported by verifiable evidence.','claim_score':15,'standards':['General green-claim quality review'],'action':'Keep green claims specific, scoped and evidence-backed.','problematic_terms':[]}
        fs.append(enrich_green_finding(f,''))
    return sorted(fs,key=lambda f:f['claim_score'], reverse=True)

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
def is_green_negative_source(result):
    text=_external_signal_text(result)
    hard=any(t in text for t in GREEN_NEGATIVE_SIGNAL_TERMS)
    stakeholder=any(t in text for t in ['regulator','authority','watchdog','court','complaint','lawsuit','investigation','media','press','ngo','consumer authority','asa','jep','reuters','guardian','bbc','ft.com'])
    own_or_neutral=any(t in text for t in OWNED_OR_NEUTRAL_DOC_TERMS) and not hard
    positive_only=any(t in text for t in POSITIVE_NOISE_TERMS) and not hard
    return hard and stakeholder and not own_or_neutral and not positive_only

def green_negative_compact_sources(results, limit=5):
    return compact_sources([r for r in results if is_green_negative_source(r)], limit)

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

def calc_green_score(findings, sector, ext, page_text, audience):
    claim=max(f.get('claim_score',0) for f in findings)
    high_claims=len([f for f in findings if f.get('risk')=='High'])
    no_major=findings and findings[0].get('type','').lower().startswith('no major')
    claim_wording=min(100,round(claim*1.25)) if not no_major else 15
    substantiation, evidence_notes=green_evidence_signal_score(page_text, findings)
    evidence_gap=25 if no_major else max(0,100-substantiation)
    external_context=green_external_context_risk(ext)
    external_score=external_context.get('score',0)
    sector_score=sector_environment_score(sector)
    # Consumer-facing material receives full EmpCo sensitivity. Investor reports are still scanned but capped unless wording is also consumer-like.
    audience_label=audience.get('audience','')
    audience_factor=1.0 if ('Client-facing' in audience_label or 'Consumer-facing' in audience_label or 'commercial' in audience_label.lower()) else 0.85 if ('Mixed' in audience_label or 'unclear' in audience_label.lower()) else 0.70
    raw=round((claim_wording*0.30 + evidence_gap*0.30 + external_score*0.25 + sector_score*0.15)*audience_factor)
    if no_major: raw=min(raw,28 if external_score<40 else 38)
    if high_claims==0: raw=min(raw,49)
    if evidence_gap<45: raw=min(raw,49)
    if external_score<40: raw=min(raw,59)
    if raw>=80 and not (high_claims>=2 and evidence_gap>=70 and external_score>=65): raw=min(raw,74)
    comps={'claim_wording_risk':claim_wording,'substantiation_risk':evidence_gap,'external_context_risk':external_score,'sector_baseline_risk':sector_score,'substantiation_score':substantiation,'evidence_notes':evidence_notes,'audience_factor':audience_factor}
    return max(0,min(100,raw)), comps, external_context

def has_regulatory_green_signal(findings, audience):
    aud=(audience or {}).get('audience','').lower()
    consumer=('client-facing' in aud or 'consumer-facing' in aud or 'commercial' in aud or 'mixed' in aud)
    if not consumer:
        return False
    for f in findings or []:
        if f.get('blacklisted_practice_indicator'):
            return True
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('analysis','')+' '+f.get('regulatory_signal','')).lower()
        if any(x in t for x in ['generic environmental','climate-neutrality','offsetting','comparative environmental','future environmental','sustainability label','absolute or purity','legal requirement','eco-friendly','carbon neutral','climate neutral','net zero','recyclable','sustainable']):
            return True
    return False

def has_forced_labour_regulatory_signal(findings):
    for f in findings or []:
        t=(f.get('type','')+' '+f.get('claim','')+' '+f.get('analysis','')).lower()
        if any(x in t for x in ['forced labour','forced-labour','modern slavery','traceability','supplier','supply chain','responsible sourcing','child labour','import','export']):
            return True
    return False

def recalibrate_dimension_score(raw_score, components, findings, targeted_sources, regulatory_signal=False, dimension='green'):
    """Recalibrated dimension score.

    Previous versions used fixed caps such as 48/100 when there were no high-risk
    claims or when evidence-gap risk was below a threshold. That could make unrelated
    companies receive identical 48/100 scores across Global, Green and Social.

    The method keeps a conservative philosophy, but uses a continuous score instead of
    fixed plateau values. The result varies with claim wording, evidence gap,
    retained external signals, sector exposure, number of detected claim types and
    direct EmpCo / Forced Labour Regulation indicators.
    """
    comps=dict(components or {})
    evidence_gap=int(comps.get('substantiation_risk',0) or 0)
    claim_wording=int(comps.get('claim_wording_risk',0) or 0)
    sector_score=int(comps.get('sector_baseline_risk',0) or 0)
    ext_count=len(targeted_sources or [])
    findings=list(findings or [])
    no_major=bool(findings and findings[0].get('type','').lower().startswith('no major'))
    material=[f for f in findings if not f.get('type','').lower().startswith('no major')]
    high_claims=len([f for f in material if f.get('risk')=='High'])
    medium_claims=len([f for f in material if f.get('risk')=='Medium'])

    # Only retained, company-specific external stakeholder sources count here.
    external_context=min(100, 16 + 14*ext_count) if ext_count else 0
    comps['external_context_risk']=external_context

    # Continuous weighted formula. Evidence and claim wording are the main drivers;
    # sector and external context are modifiers.
    base=round(claim_wording*0.34 + evidence_gap*0.32 + external_context*0.22 + sector_score*0.12)

    # Small differentiating modifiers avoid artificial plateaus.
    base += min(8, high_claims*4)
    base += min(4, medium_claims*2)
    if regulatory_signal:
        base += 7 if dimension=='green' else 5
    if ext_count>=2:
        base += 3
    if no_major:
        base -= 10

    # Conservative interpretive caps avoid treating weak or generic signals as high risk.
    if no_major:
        cap=24 + min(8, ext_count*4) + (4 if sector_score>=55 else 0)
        base=min(base, cap)
    else:
        if high_claims==0:
            cap=42 + min(10, evidence_gap//8) + min(6, external_context//18) + (4 if regulatory_signal else 0)
            base=min(base, cap)
        if evidence_gap < 25:
            base=min(base, 44 + min(6, claim_wording//20) + min(4, external_context//25))
        elif evidence_gap < 45:
            base=min(base, 56 + min(6, claim_wording//25) + min(5, external_context//20))
        if ext_count==0 and not regulatory_signal:
            base=min(base, 61 if high_claims else 55)

    # High risk requires a meaningful combination of problematic wording and weak substantiation.
    if base>=70 and not (evidence_gap>=58 and claim_wording>=62 and (regulatory_signal or ext_count>=1 or high_claims>=2)):
        base=66
    if base>=80 and not (evidence_gap>=72 and claim_wording>=75 and (ext_count>=1 or (dimension=='green' and regulatory_signal))):
        base=76

    base=max(0,min(100,int(round(base))))
    comps['score_calculation_note']='Score calculation: 34% claim wording, 32% evidence gap, 22% retained external stakeholder context, 12% sector/channel sensitivity, with regulatory and claim-count modifiers.'
    return base, comps

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
    if score<60: return prefix+'Potential greenwashing concern — evidence review needed'
    if external_score>=40 and evidence_gap>=55: return prefix+'High greenwashing risk signal — verify urgently'
    return prefix+'Potential greenwashing concern — not enough contradiction evidence for High'

def build_green_claim_inventory(findings):
    out=[]
    for f in findings:
        out.append({'dimension':'Green','claim_text':f.get('claim',''),'claim_type':f.get('type',''),'washing_type':f.get('type',''),'risk_level':f.get('risk',''),'claim_score':f.get('claim_score',0),'module':f.get('module',green_claim_module(f.get('type',''))),'risk_reason':f.get('issue',''),'analysis':f.get('issue',''),'regulatory_signal':f.get('regulatory_signal',''),'blacklisted_practice_indicator':f.get('blacklisted_practice_indicator',False),'specification_check':f.get('specification_check',{}),'evidence_questions':f.get('evidence_questions',[]),'pre_publication_decision':f.get('pre_publication_decision','Review before publication.'),'evidence_needed':green_evidence_checklist(f),'suggested_rewrite':f.get('rewrite',''),'standards':f.get('standards',[])})
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

def build_green_social_actions(green_findings, social_findings, audience):
    actions=[]
    client_facing=('Client-facing' in audience.get('audience','') or 'Consumer-facing' in audience.get('audience','') or 'commercial' in audience.get('audience','').lower())
    all_findings=(green_findings or [])+(social_findings or [])
    high_green=[f for f in (green_findings or []) if f.get('risk')=='High']
    high_social=[f for f in (social_findings or []) if f.get('risk')=='High']
    claim_types='; '.join(dict.fromkeys([f.get('type','claim') for f in all_findings if f.get('type')]))[:220]
    if client_facing or high_green:
        actions.append({'priority':'Priority 1','title':'Review client-facing green claims under EmpCo','action':f"Check the exact wording of the detected green claim areas ({claim_types or 'environmental claims'}) on websites/product pages/folders. For each claim, document scope, product coverage, methodology, evidence source, verification basis and limitations before reuse."})
    else:
        actions.append({'priority':'Priority 1','title':'Confirm which scanned claims are client-facing','action':'Separate website/product/folder wording from annual or sustainability report language. Treat client-facing claims as higher priority for EmpCo-style substantiation and approval controls.'})
    if high_social:
        forced=any(('forced' in f.get('type','').lower() or 'modern slavery' in f.get('type','').lower() or 'supply' in f.get('type','').lower()) for f in high_social)
        if forced:
            actions.append({'priority':'Priority 2','title':'Validate forced-labour and supplier claims','action':'For supplier, responsible-sourcing, modern-slavery or forced-labour wording, prepare evidence on product/supplier traceability, risk assessment by geography/product, mitigation, grievance/remediation and withdrawal/customs response readiness under Regulation (EU) 2024/3015.'})
        else:
            actions.append({'priority':'Priority 2','title':'Substantiate high-priority social claims','action':'For the detected social claim areas, collect stakeholder scope, KPIs, grievance/remedy evidence, audit or workforce data and clear limits to avoid overstatement.'})
    actions.append({'priority':'Priority 3','title':'Build a claim evidence file','action':'Create one evidence file per priority claim with the approved wording, source URL/document, owner, evidence link, date, legal/compliance review status and review deadline.'})
    if any('comparative' in f.get('type','').lower() for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Check comparative green claims','action':'For reduced impact, lower emissions or better product wording, identify the comparator, baseline year, methodology, equivalent product basis and data date.'})
    if any(('climate' in f.get('type','').lower() or 'offset' in f.get('type','').lower() or 'net zero' in f.get('claim','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Clarify climate and offset claims','action':'Separate actual emission reductions from offsetting/compensation, and disclose scopes, baseline, residual emissions, implementation plan and progress indicators.'})
    if any(('label' in f.get('type','').lower() or 'certification' in f.get('type','').lower()) for f in green_findings or []):
        actions.append({'priority':'Priority 4','title':'Verify labels and certifications','action':'Name the scheme owner, criteria, certification scope, verification body and validity period for any green/social label or certification reference.'})
    actions.append({'priority':'Priority 5','title':'Align reporting and marketing language','action':'Use sustainability and annual reports as supporting evidence, but avoid copying broad report language into consumer-facing pages unless the claim is specific, current, substantiated and audience-appropriate.'})
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
        vals=[f.get('type','claim') for f in fs or [] if not f.get('type','').lower().startswith('no major')]
        return ', '.join(vals[:3]) if vals else 'no material claim type detected'
    def targeted_count(ext):
        return len(ext.get('targeted_negative_sources') or []) if ext else 0
    gf=claim_names(green_fs); sf=claim_names(social_fs)
    ge='; '.join((green_components or {}).get('evidence_notes',[])[:1])
    se='; '.join((social_components or {}).get('evidence_notes',[])[:1])
    audience_note='Client-facing sources increase EmpCo relevance.' if 'Client-facing' in audience.get('audience','') else 'Investor/internal sources are mainly treated as evidence and consistency context.'
    return {
        'green': {
            'score': green_score,
            'summary': f'Green score {green_score}/100: driven by {gf}. Claim wording {green_splits.get("claim_wording_risk",0)}/100, evidence gap {green_splits.get("substantiation_risk",0)}/100, external context {green_splits.get("external_context_risk",0)}/100, sector exposure {green_splits.get("sector_baseline_risk",0)}/100. {ge} {audience_note}',
            'key_drivers': [
                f'Detected green claim areas: {gf}.',
                f'Evidence-gap driver: {green_splits.get("substantiation_risk",0)}/100.',
                f'External green signals retained after company-owned-source filtering: {targeted_count(green_ext)}.',
                f'Sector exposure for environmental claims: {sector.get("level","Medium")}.'
            ]
        },
        'social': {
            'score': social_score,
            'summary': f'Social score {social_score}/100: driven by {sf}. Claim wording {social_splits.get("claim_wording_risk",0)}/100, evidence gap {social_splits.get("substantiation_risk",0)}/100, external context {social_splits.get("external_context_risk",0)}/100, sector exposure {social_splits.get("sector_baseline_risk",0)}/100. {se} Forced-labour/product-supply-chain wording receives higher regulatory weight where relevant.',
            'key_drivers': [
                f'Detected social claim areas: {sf}.',
                f'Evidence-gap driver: {social_splits.get("substantiation_risk",0)}/100.',
                f'External social signals retained after company-owned-source filtering: {targeted_count(social_ext)}.',
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

def extract_pdf_text_best_effort(data):
    # Lightweight best-effort extraction without external dependencies. Text-based PDFs may yield usable strings;
    # scanned/image PDFs will not. For reliable scans, upload a text extract or DOCX.
    try:
        raw=data.decode('latin-1',errors='ignore')
        candidates=re.findall(r'\(([^()]{3,250})\)', raw)
        txt=' '.join(candidates)
        txt=txt.replace('\\n',' ').replace('\\r',' ').replace('\\t',' ')
        txt=re.sub(r'\\[()\\]', '', txt)
        txt=re.sub(r'\s+', ' ', txt).strip()
        return txt[:90000]
    except Exception:
        return ''

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
    txt=re.sub(r'\s+', ' ', txt or '').strip()
    if len(txt)<80:
        raise ValueError('The uploaded document could not be parsed into enough text. Please upload a text-based DOCX/HTML/TXT version or paste an extract into a text file.')
    return txt[:90000]

def fetch_document_text(url):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or is_private(p.hostname):
        return ''
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 GreenSocialClaimsAssessment/40.0','Accept':'text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'},method='GET')
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

def analyse_uploaded_document(filename, text):
    source='Uploaded internal document: '+(filename or 'document')
    comp=infer_company(filename or source, text)
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
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext,text)
    social_reg=has_forced_labour_regulatory_signal(social_fs)
    social_score, social_components = recalibrate_dimension_score(social_score, social_components, social_fs, social_targeted, social_reg, 'social')
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext,text,audience)
    green_reg=has_regulatory_green_signal(green_fs,audience)
    green_score, green_components = recalibrate_dimension_score(green_score, green_components, green_fs, green_targeted, green_reg, 'green')
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
        'overall_score':overall,'overall_risk':level(overall),'global_score':overall,'global_risk':level(overall),'green_score':green_score,'green_risk':level(green_score),'green_conclusion':green_conclusion,'social_score':social_score,'social_risk':level(social_score),'social_conclusion':social_conclusion,'screening_conclusion':f'Global: {level(overall)} | Green: {level(green_score)} | Social: {level(social_score)}','methodology':methodology,'company':comp,'sector':sec,'context':ctx,'document_audience':audience,'findings':all_claims,'green_findings':green_fs,'social_findings':social_fs,'documents_checked':documents_checked,'channel_analysis':build_channel_analysis(documents_checked),'related_source_notes':[],'report':{'summary':summary,'rationale':methodology,'rewrite_guidance':'Make green and social claims specific, scoped, evidenced and audience-appropriate.','pages_reviewed':[source],'standards_overview':EMPCO_LENS+STANDARDS},'assessment_summary_specific':summary,'concise_standards_lens':EMPCO_LENS,'merged_claims':all_claims,'claim_inventory':all_claims,'regulatory_risk_summary':build_regulatory_risk_summary(green_fs,social_fs,audience),'claim_modules_summary':build_claim_modules_summary(green_fs,social_fs),'federation_pilot_output':federation_pilot_output(green_fs,social_fs,overall,green_score,social_score),'external_research':{'green':dict(green_ext,compact_sources=green_targeted,targeted_negative_sources=green_targeted),'social':dict(social_ext,compact_sources=social_targeted,targeted_negative_sources=social_targeted),'summary':'Internal-document scan only. No public-source or website content is included.'},'green_external_context_assessment':green_external_context,'social_external_context_assessment':{'score':0,'note':'Not assessed for internal-document scans.'},'score_components':{'green':green_components,'social':social_components},'split_scores':{'global_score':overall,'green_risk_score':green_score,'social_risk_score':social_score,'green':green_splits,'social':social_splits},'why_score':{'global':f'Global score is {overall}/100. It reflects only the uploaded internal document and is a weighted combination of the green and social scores.','green':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['green']['summary'],'social':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience)['social']['summary'],'audience':audience.get('note',''),'interpretation':'This is an assessment signal, not a legal finding.'},'score_driver_details':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext,sec,ctx)+(['High-sensitivity green claims require EmpCo-style substantiation and wording controls.' ] if any(f.get('risk')=='High' for f in green_fs) else []),'red_flags_by_dimension':split_red_flags_by_dimension(green_fs,social_fs,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),'company_action_plan':build_green_social_actions(green_fs,social_fs,audience),'engagement_questions':build_engagement_questions(social_fs,social_ext),'confidence':{'level':'Medium','reasons':['Uploaded document was scanned as a standalone source.','External public-source search was not performed for this internal-document scan.']},'disclaimer':'Indicative first-pass sustainability claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use.','analysed_text_excerpt':text[:2200],'quality_improvements':['Maintain a sustainability claims register distinguishing green and social claims, claim owner, evidence file and review date.','Attach objective evidence, same-medium specification, methodology, limitations and approval owner to each claim.'],'ai_used':False,'ai_note':''}

def analyse_url_v27(raw):
    original_url=norm_url(raw); fallback_note=''; related_notes=[]
    try:
        txt,pages,related_notes=crawl_with_related_sites(original_url); url=original_url
    except Exception as first_error:
        fallback_url=replace_tld_with_be(original_url)
        if fallback_url:
            try:
                txt,pages,related_notes=crawl_with_related_sites(fallback_url); url=fallback_url; fallback_note=f'The original .com website was not accessible. The scan was automatically performed on {fallback_url}.'
            except Exception as second_error:
                raise ValueError(f'The .com website could not be accessed and the .be fallback also failed. Original error: {first_error}. Fallback error: {second_error}.')
        else:
            raise first_error
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
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext_scoring,txt)
    social_external_context = strict_external_context_risk({'results':social_targeted}, comp.get('company',''))
    social_reg=has_forced_labour_regulatory_signal(social_fs)
    social_score, social_components = recalibrate_dimension_score(social_score, social_components, social_fs, social_targeted, social_reg, 'social')
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext_scoring,txt,audience)
    green_reg=has_regulatory_green_signal(green_fs,audience)
    green_score, green_components = recalibrate_dimension_score(green_score, green_components, green_fs, green_targeted, green_reg, 'green')
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
    methodology='Sustainability Scan. The assessment separates green and social claim signals. Green claims are assessed through an EmpCo / Directive (EU) 2024/825 lens for consumer-facing environmental claims, with explicit modules for generic claims, carbon/offsetting, labels/icons, future claims, comparisons, legal-requirement claims and same-medium specification. Social claims are assessed through claim wording, evidence gap, external contradictory context and sector exposure, with a specific Forced Labour Regulation / Regulation (EU) 2024/3015 lens for product, supplier, import/export, traceability, forced-labour and modern-slavery claims. Clear indications of EmpCo or Forced Labour Regulation risk receive a higher weighting than broader responsible-business claims mainly linked to OECD Guidelines, UNGC or UNGP expectations. External public-source signals exclude company-owned websites, policies, reports and supplier documents; those may be used as evidence but not as external stakeholder signals. Sector exposure is included as a baseline sensitivity factor but should not create a High-risk result without problematic claim wording, evidence gaps or contradictory context.'
    summary=(f"{comp['company']} receives a global sustainability scan score of {overall}/100. "
             f"Green risk: {green_score}/100 ({green_conclusion}). Social risk: {social_score}/100 ({social_conclusion}). "
             f"Document/channel classification: {audience['audience']} — {audience['note']}" + (" "+"; ".join(related_notes) if related_notes else ""))
    return {'version':APP_VERSION,'source_label':url,'original_url':original_url,'fallback_note':fallback_note,'analysis_date':datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
        'overall_score':overall,'overall_risk':level(overall),'global_score':overall,'global_risk':level(overall),
        'green_score':green_score,'green_risk':level(green_score),'green_conclusion':green_conclusion,
        'social_score':social_score,'social_risk':level(social_score),'social_conclusion':social_conclusion,
        'screening_conclusion':f'Global: {level(overall)} | Green: {level(green_score)} | Social: {level(social_score)}',
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
        'why_score':{'global':f'Global score is {overall}/100. It is a weighted combination of the green score ({green_score}/100) and social score ({social_score}/100), capped so it cannot exceed the highest dimension score. Direct EmpCo or Forced Labour Regulation risk signals can raise the relevant dimension score, while broader OECD/UNGC/UNGP expectations are weighted less strongly.',
                     'green':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience)['green']['summary'],
                     'social':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience)['social']['summary'],
                     'audience':audience['note'],'interpretation':'This is an assessment signal, not a legal finding. EmpCo relevance is strongest for consumer-facing commercial communications. The score methodology uses continuous weighting so results vary by claim type, evidence gap, communication channel, sector sensitivity and retained external stakeholder context.'},
        'score_driver_details':score_driver_details(green_score,social_score,green_fs,social_fs,green_splits,social_splits,green_components,social_components,dict(green_ext, targeted_negative_sources=green_targeted),dict(social_ext, targeted_negative_sources=social_targeted),sec,audience),
        'stakeholder_red_flags':regulatory_red_flags(green_fs,social_fs,audience)+build_red_flags(social_fs,social_ext,sec,ctx)+(['High-sensitivity green claims require EmpCo-style substantiation and consumer-facing wording controls.' ] if any(f.get('risk')=='High' for f in green_fs) else []),
        'red_flags_by_dimension':split_red_flags_by_dimension(green_fs,social_fs,dict(green_ext,targeted_negative_sources=green_targeted),dict(social_ext,targeted_negative_sources=social_targeted),sec,audience),
        'company_action_plan':build_green_social_actions(green_fs,social_fs,audience),'engagement_questions':build_engagement_questions(social_fs,social_ext)+['Which green claims are consumer-facing, and what objective evidence file supports each claim under EmpCo-style controls?','For products or supply chains, what forced-labour risk assessment, traceability evidence, remediation process and withdrawal/customs response procedure support the claim under Regulation (EU) 2024/3015?'],
        'confidence':build_confidence(pages,social_ext,social_fs),'disclaimer':'Indicative first-pass sustainability claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use. External search results are review signals that require manual verification.',
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
GREEN_CLAIMS=[
 (['eco-friendly','environmentally friendly','environmentally responsible','planet friendly','better for the planet','good for the planet','ecological','climate friendly','climate-friendly','green product','green choice','eco choice','eco product','sustainable product','sustainable choice','100% sustainable','fully sustainable'],'Generic environmental claim','High','EmpCo risk: generic environmental claims can be prohibited in consumer-facing communication where the claim is not clearly and prominently specified on the same medium or backed by recognised excellent environmental performance relevant to the claim as a whole.','Replace generic wording with a precise, evidence-backed claim stating the exact product attribute, scope, geography, methodology, period and limitations.'),
 (['carbon neutral','climate neutral','co2 neutral','co₂ neutral','net zero product','carbon negative','carbon positive','climate positive','carbon compensated','climate compensated','offset-based','offsetting','compensated emissions','reduced climate impact'],'Climate-neutrality or offsetting claim','High','EmpCo risk: product-level claims that state or imply neutral, reduced or positive climate impact based on greenhouse-gas offsetting are high-priority blacklisted-practice indicators.','Avoid product-level neutrality wording based on offsets. Separate actual emissions reductions from offsets and disclose scopes, baseline, methodology, residual emissions and progress.'),
 (['greener than','more sustainable than','more eco-friendly than','lower impact than','lowest emissions','best environmental','less harmful than','lower emissions than','reduced emissions compared','reduced impact compared'],'Comparative environmental claim','High','EmpCo risk: environmental comparisons require information on the comparison method, comparator, products and suppliers compared, data sources and update process.','State the comparator, baseline, methodology, scope, data date and update mechanism; avoid vague superiority claims.'),
 (['eco label','ecolabel','sustainability label','self-declared sustainability label','green certified','eco certified','planet approved','responsible choice label','green badge','eco badge'],'Sustainability label / certification claim','High','EmpCo risk: self-declared sustainability labels are blacklisted unless based on an independent, transparent certification scheme or public-authority label. Icons, symbols and trust marks may fall within this category.','Name the scheme owner, criteria, independence, audit basis, scope and validity period. Remove self-declared labels or clarify them as non-certification claims.'),
 (['we will be net zero','we aim to be net zero','we are working towards net zero','net zero by 2030','net zero by 2040','net zero by 2050','climate positive by','carbon neutral by','sustainable future','climate ambition','climate roadmap'],'Future environmental-performance claim','High','EmpCo risk: future environmental-performance claims require clear, objective, publicly available and verifiable commitments supported by a realistic implementation plan.','Add a public implementation plan, milestones, resources, governance, progress indicators, verification basis and scope limitations.'),
 (['all natural','100% natural','chemical free','zero impact','no impact','zero waste','waste free','pollution free','fully recyclable','100% recyclable','completely biodegradable','fully biodegradable'],'Absolute or purity environmental wording','High','EmpCo risk: absolute environmental wording creates a high evidence burden and can mislead when scope, conditions or limitations are missing.','Qualify the claim and specify exact attribute, scope, conditions, test method, limitations and evidence.'),
 (['compliant with environmental law','meets legal requirements','according to legal standards','required by law','legal requirement','eu compliant','regulation compliant'],'Legal requirement presented as green benefit','High','EmpCo risk: presenting requirements imposed by law as a distinctive environmental feature is a blacklisted-practice indicator.','Do not present legal compliance as a differentiating sustainability benefit. Separate legal compliance from voluntary improvements.'),
 (['green leaf','leaf icon','tree icon','water drop','waterdrop','planet icon','earth icon','eco badge','green badge','environmental icon','recycled badge','sustainability badge'],'Visual green-claim indicator','Medium','EmpCo risk: pictorial, graphic or symbolic representations can imply environmental benefits and should be assessed like written claims.','Check whether the icon or badge implies a specific environmental benefit and connect it to clear, prominent and evidenced wording.'),
]

# Narrower social taxonomy. Supplier/customer/community mentions are not retained unless
# they imply assurance, coverage, control, certification, traceability, rights protection or
# equivalent high-stakes social performance.
CLAIMS=[
 (['forced labour free','forced labor free','free from forced labour','free from forced labor','no forced labour','no forced labor','modern slavery free','child labour free','child labor free','no child labour','no child labor','forced labour due diligence','forced labor due diligence','product traceability','supplier traceability','import controls'],'Forced-labour product or supply-chain claim','High','Forced Labour Regulation risk: the wording may imply product, supplier or supply-chain assurance against forced labour. Such claims require strong traceability, risk assessment, mitigation, remediation and withdrawal/customs response readiness.','Scope the wording and disclose a risk-based due-diligence process, product/supplier traceability, escalation and remediation steps.'),
 (['all suppliers audited','all suppliers are audited','all suppliers certified','all suppliers are certified','all suppliers comply','all suppliers are compliant','all suppliers meet','100% of suppliers','fully traceable supply chain','fully audited supply chain','ethical sourcing','responsible sourcing','certified suppliers','audited suppliers','traceable suppliers','supplier code compliance','certified against our supplier code','comply with our supplier code'],'Supply-chain or supplier-responsibility claim','High','The wording may imply broad supplier control or responsible value-chain coverage. It is problematic where supplier tiers, audit quality, worker voice, findings and remediation are not clear.','Scope the claim to covered supplier tiers and disclose coverage, methodology, findings and corrective-action closure rates.'),
 (['human rights compliant','respect human rights across our value chain','protect human rights across our value chain','living wage across our supply chain','decent work guaranteed','guaranteed labour rights','guaranteed labor rights','no discrimination','zero discrimination','equal pay guaranteed'],'Human-rights or labour-rights claim','High','The claim refers to sensitive rights topics and may overstate outcomes or control without due diligence, grievance channels, tracking and remedy.','State the due-diligence process, salient risks, coverage, grievance channels, tracking, limits and remediation process.'),
 (['safe workplace guaranteed','zero accidents','zero harm','injury free','guaranteed safe workplace','no workplace injuries'],'Health, safety or worker-welfare claim','High','Absolute safety or welfare wording creates a high evidence burden and can overstate outcomes, particularly where contractors or suppliers are involved.','Use scoped wording linked to incident data, controls, coverage, training and corrective actions.'),
 (['all employees included','fully inclusive workplace','100% inclusive','guaranteed equal opportunities','no pay gap','zero pay gap'],'Diversity, equality and inclusion claim','Medium','Absolute inclusion, equality or pay-gap wording may overstate outcomes unless backed by data, scope, baseline and progress evidence.','Add workforce data, baseline, scope, limitations, methodology and progress indicators.'),
]

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

def detect_claims(text):
    low=(text or '').lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            claim_excerpt=_sentence_window(text,trig)
            if not _has_real_claim_context(claim_excerpt, typ, trig):
                continue
            seen.add(typ)
            # Claim wording scores are deliberately moderate. High-risk wording is a
            # signal for review, not a finding of social washing by itself.
            score=62 if typ=='Forced-labour product or supply-chain claim' else (56 if risk=='High' else 38)
            fs.append({'type':typ,'risk':risk,'claim':claim_excerpt,'issue':issue,'rewrite':rewrite,'claim_score':score,'standards':standards_for_claim(typ),'action':('Document product/supplier traceability, forced-labour risk assessment, mitigation, remediation and withdrawal/customs response readiness.' if typ=='Forced-labour product or supply-chain claim' else 'Substantiate the claim with scope, evidence, reporting period, limitations and remediation steps.'),'problematic_terms':problematic_terms_for_finding(claim_excerpt,typ)})
    if not fs:
        fs.append({'type':'No material problematic social claim retained','risk':'Low','claim':'No exact problematic social claim was retained from the reviewed material.','issue':'The scan did not retain a material high-risk social claim. Neutral references to suppliers, people, communities or employees are not scored unless they imply assurance, control, full coverage, certification, traceability, due diligence or other high-stakes social performance.','rewrite':'No rewrite is needed unless the company wants to make a specific social-performance claim.','claim_score':8,'standards':['General claim-quality review'],'action':'Keep any future social claims specific, scoped and evidenced.','problematic_terms':[]})
    return sorted(fs,key=lambda f:f['claim_score'],reverse=True)

def detect_green_claims(text):
    low=(text or '').lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in GREEN_CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            claim_excerpt=_sentence_window(text,trig)
            if not _has_real_claim_context(claim_excerpt, typ, trig):
                continue
            seen.add(typ)
            # Direct EmpCo blacklisted-practice indicators receive more weight, but
            # one isolated claim should not create an extreme score by itself.
            if any(x in typ.lower() for x in ['climate','legal requirement']):
                score=66
            elif any(x in typ.lower() for x in ['generic','label','comparative','future','absolute']):
                score=60
            else:
                score=42
            f={'dimension':'green','type':typ,'risk':risk,'claim':claim_excerpt,'issue':issue,'rewrite':rewrite,'claim_score':score,'standards':['EmpCo / Directive (EU) 2024/825','UCPD misleading commercial practices'],'action':'Substantiate the green claim with scope, objective evidence, methodology, limits, same-medium specification and verification.','problematic_terms':problematic_terms_for_finding(claim_excerpt,typ)}
            fs.append(enrich_green_finding(f,trig))
    if not fs:
        f={'dimension':'green','type':'No material problematic green claim retained','risk':'Low','claim':'No exact problematic green claim was retained from the reviewed material.','issue':'The scan did not retain a direct EmpCo blacklisted-practice indicator or high-sensitivity environmental claim. General sustainability context is not scored as a problematic claim unless it contains specific risk wording.','rewrite':'No rewrite is needed unless the company wants to make a specific environmental claim.','claim_score':8,'standards':['General green-claim quality review'],'action':'Keep environmental claims specific, scoped and evidence-backed.','problematic_terms':[]}
        fs.append(enrich_green_finding(f,''))
    return sorted(fs,key=lambda f:f['claim_score'], reverse=True)

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
    comps['score_calculation_note']='Score calculation: material problematic claim wording, evidence gap, retained negative external stakeholder context and sector/channel sensitivity. Isolated claims are capped unless supported by stronger regulatory and external-context factors.'
    return base, comps

def calc_green_score(findings, sector, ext, page_text, audience):
    material=[f for f in findings or [] if not (f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'))]
    claim=max([f.get('claim_score',0) for f in material] or [8])
    no_material=len(material)==0
    claim_wording=min(100,round(claim*1.15)) if not no_material else 8
    substantiation, evidence_notes=green_evidence_signal_score(page_text, findings)
    evidence_gap=15 if no_material else max(0,100-substantiation)
    external_context=green_external_context_risk(ext)
    external_score=external_context.get('score',0)
    sector_score=sector_environment_score(sector)
    audience_label=audience.get('audience','')
    audience_factor=1.0 if ('Client-facing' in audience_label or 'Consumer-facing' in audience_label or 'commercial' in audience_label.lower()) else 0.85 if ('Mixed' in audience_label or 'unclear' in audience_label.lower()) else 0.65
    raw=round((claim_wording*0.30 + evidence_gap*0.30 + external_score*0.25 + sector_score*0.15)*audience_factor)
    if no_material: raw=min(raw,22 if external_score<40 else 32)
    comps={'claim_wording_risk':claim_wording,'substantiation_risk':evidence_gap,'external_context_risk':external_score,'sector_baseline_risk':sector_score,'substantiation_score':substantiation,'evidence_notes':evidence_notes,'audience_factor':audience_factor}
    return max(0,min(100,raw)), comps, external_context

def calc_score(findings,sector,context,external_research=None,page_text=""):
    material=[f for f in findings or [] if not (f.get('type','').lower().startswith('no material') or f.get('type','').lower().startswith('no major'))]
    claim=max([f.get('claim_score',0) for f in material] or [8])
    high_claims=len([f for f in material if f.get('risk')=='High'])
    no_material=len(material)==0
    claim_wording=min(100,round(claim*1.15)) if not no_material else 8
    substantiation, evidence_notes=evidence_signal_score(page_text, findings)
    evidence_gap=15 if no_material else max(0,100-substantiation)
    external_context=strict_external_context_risk(external_research or {}, "")
    external_score=external_context.get('score',0)
    sector_score={"Low":10,"Medium":35,"High":60}.get(sector.get("level","Medium"),35)
    raw=round(claim_wording*0.30 + evidence_gap*0.30 + external_score*0.25 + sector_score*0.15)
    external_mod, external_note=external_relevance_score(findings, external_research or {})
    if no_material:
        raw=min(raw,22 if external_score<40 else 32)
    if len(material)==1 and external_score<40:
        raw=min(raw,48)
    if raw>=70 and not (high_claims>=2 or external_score>=50):
        raw=64
    raw=max(0,min(100,raw))
    return raw, external_mod, external_note, evidence_quality_credit(page_text, findings), {"claim_wording_risk":claim_wording,"substantiation_risk":evidence_gap,"external_context_risk":external_score,"sector_baseline_risk":sector_score,"substantiation_score":substantiation,"evidence_notes":evidence_notes}

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

class Handler(BaseHTTPRequestHandler):
    def _send(self,body,ctype="text/html; charset=utf-8",status=200):
        if isinstance(body,str): body=body.encode()
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers(); self.wfile.write(body)
    def _json(self,d,status=200): self._send(json.dumps(d,ensure_ascii=False,indent=2),"application/json; charset=utf-8",status)
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_OPTIONS(self): self._json({"ok":True})
    def do_GET(self):
        if self.path=="/" or self.path.startswith("/?"): self._send((APP_DIR/"frontend.html").read_text(encoding="utf-8"))
        elif self.path=="/methodology.pdf":
            pdf=APP_DIR/"methodology.pdf"
            if pdf.exists(): self._send(pdf.read_bytes(),"application/pdf")
            else: self._json({"error":"Methodology PDF not found"},404)
        elif self.path=="/api/health": self._json({"status":"ok","version":APP_VERSION,"ai_configured":bool(OPENAI_API_KEY),"tavily_configured":bool(TAVILY_API_KEY),"google_search_configured":bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX),"google_api_key_configured":bool(GOOGLE_SEARCH_API_KEY),"google_cx_configured":bool(GOOGLE_SEARCH_CX)})
        else: self._json({"error":"Not found"},404)
    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length",0)); data=json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if self.path=="/api/scan/url":
                u=data.get("url","")
                if not u: return self._json({"error":"No URL provided"},400)
                return self._json(analyse_url(u))
            if self.path=="/api/scan/document":
                filename=data.get("filename","uploaded_document")
                content=data.get("content_base64","")
                if not content: return self._json({"error":"No document content provided"},400)
                txt=decode_uploaded_document(filename, content, data.get("mime_type",""))
                return self._json(analyse_uploaded_document(filename, txt))
            self._json({"error":"Unknown endpoint"},404)
        except Exception as e: self._json({"error":str(e)},500)

def main():
    print(f"Sustainability Scan {APP_VERSION}"); print(f"Serving on http://{HOST}:{PORT}"); print("Tavily configured:",bool(TAVILY_API_KEY)); print("Google Search configured:",bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)); print("AI configured:",bool(OPENAI_API_KEY)); HTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()
