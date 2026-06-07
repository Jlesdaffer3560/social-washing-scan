#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime

APP_VERSION="hostable_v35_professional_assessment"
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
  (["supply chain","value chain","all suppliers","supplier","responsible sourcing","ethical sourcing","audited","certified","traceable","supplier code"],"Supply-chain or supplier-responsibility claim","High","The claim may imply supplier control or responsible value-chain coverage without showing supplier tiers, audit quality, worker voice or remediation.","Scope the claim, for example: 'We assess higher-risk suppliers through a risk-based process and disclose supplier coverage, key findings and corrective-action closure rates.'"),
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
        if tag.lower() in self.skip_tags: self.skip=True
        if tag.lower()=="a":
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

def related_company_sites(url, max_sites=2):
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
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 GreenSocialClaimsAssessment/35.0","Accept":"text/html,application/xhtml+xml"})
    with urlopen(req,timeout=12,context=ssl.create_default_context()) as r:
        if "html" not in r.headers.get("content-type","").lower(): raise ValueError("URL does not return an HTML page.")
        return r.read(2000000).decode("utf-8",errors="ignore")
def same_domain(u,base):
    h=urlparse(u).hostname or ""
    return h==base or h.endswith("."+base)
def relevant(h):
    h=h.lower()
    return any(k in h for k in ["sustain","responsib","people","human","rights","divers","inclusion","supplier","ethic","impact","community","accessibility","safety","annual","report","esg"])
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
    with urlopen(req,timeout=12) as r: data=json.loads(r.read().decode("utf-8",errors="ignore"))
    return [{"title":i.get("title",""),"url":i.get("url",""),"content":i.get("content",""),"score":i.get("score",0)} for i in data.get("results",[])]

def google_search(query, max_results=5):
    """Google Custom Search JSON API fallback. Requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return []
    from urllib.parse import urlencode
    params=urlencode({"key":GOOGLE_SEARCH_API_KEY,"cx":GOOGLE_SEARCH_CX,"q":query,"num":max(1,min(max_results,10))})
    req=Request("https://www.googleapis.com/customsearch/v1?"+params,headers={"User-Agent":"Mozilla/5.0 GreenSocialClaimsAssessment/35.0"},method="GET")
    with urlopen(req,timeout=12) as r:
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
    if "supplier" in joined or "supply" in joined: themes.update(["supplier labour rights controversy", "forced labour supply chain", "audit failure worker voice remediation", "EU forced labour regulation supply chain product import"])
    if "forced" in joined or "modern slavery" in joined: themes.update(["forced labour products regulation investigation", "modern slavery supply chain import ban", "forced labour product withdrawal customs EU"])
    if "human" in joined or "labour" in joined or "labor" in joined: themes.update(["human rights complaint", "labour rights lawsuit", "modern slavery forced labour"])
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
    for q in qs[:5]:
        res,attempts=search_public_sources(q,3)
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
def detect_claims(text):
    low=text.lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            seen.add(typ); score=72 if typ=="Forced-labour product or supply-chain claim" else (56 if risk=="High" else 32)
            fs.append({"type":typ,"risk":risk,"claim":snip(text,trig),"issue":issue,"rewrite":rewrite,"claim_score":score,"standards":standards_for_claim(typ),"action":("Document product/supplier traceability, forced-labour risk assessment, mitigation, remediation and withdrawal/customs response readiness." if typ=="Forced-labour product or supply-chain claim" else "Substantiate the claim with scope, evidence, reporting period, limitations and remediation steps.")})
    if not fs: fs.append({"type":"No major high-risk social claim detected","risk":"Low","claim":text[:320]+("..." if len(text)>320 else ""),"issue":"The crawler did not detect obvious high-risk social-claim wording in the reviewed company pages.","rewrite":"Keep social claims specific, scoped and supported by measurable evidence.","claim_score":18,"standards":["General claim-quality review"],"action":"Keep the claim specific, scoped and supported by measurable evidence."})
    return sorted(fs,key=lambda f:f["claim_score"],reverse=True)
def level(score):
    return "Very high" if score>=80 else "High" if score>=60 else "Medium" if score>=30 else "Low"
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
    if any(("forced" in f.get("type","").lower() or "modern slavery" in f.get("type","").lower()) for f in findings): flags.append("Forced-labour or modern-slavery claims require product/supplier traceability, risk assessment, remediation and EU Forced Labour Regulation response readiness.")
    if any(("human" in f.get("type","").lower() or "labour" in f.get("type","").lower() or "labor" in f.get("type","").lower()) for f in findings): flags.append("Human-rights or labour-rights claims require evidence of due diligence, grievance channels and remedy.")
    if ext.get("enabled") and ext.get("results"): flags.append("External public-source signals were found and should be verified before relying on the company's wording.")
    if sector.get("level")=="High": flags.append("The sector has structurally higher exposure to labour, supplier, worker or vulnerable-stakeholder issues.")
    if context.get("level") in ["High","Very high"]: flags.append("Company/context sensitivity is elevated and should be considered in stakeholder due diligence.")
    if not flags: flags.append("No major stakeholder red flag was detected from available website and public-source signals, but manual verification remains necessary.")
    return flags[:6]

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
    "forced labour","forced labor","child labour","child labor","modern slavery",
    "lawsuit","court","complaint","controversy","strike","union","regulator",
    "regulatory","discrimination","human rights","labour rights","labor rights",
    "supplier","supply chain","wage","grievance","allegation","criticism",
    "investigation","fine","sanction","breach","violation","misconduct",
    "accessibility","customer protection","workers","unsafe","audit failure"
]
POSITIVE_NOISE_TERMS = [
    "award","wins","recognised","recognized","partnership","sponsor","donation",
    "new product","launches","growth","profit","revenue","appointment","campaign"
]
def is_negative_external_source(result):
    text = (result.get("title","") + " " + result.get("content","") + " " + result.get("url","")).lower()
    has_negative = any(t in text for t in NEGATIVE_SIGNAL_TERMS)
    has_positive_noise = any(t in text for t in POSITIVE_NOISE_TERMS)
    return has_negative and not (has_positive_noise and not has_negative)
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
    return bool(terms) and any(t in text for t in terms)

def is_company_owned_source(result, company_name):
    """Exclude company-owned websites/documents from external public-source signals.
    These pages may still be used as reviewed documents or evidence sources, but not as external signals.
    """
    host=(urlparse(result.get('url','')).hostname or '').lower().replace('www.','')
    if not host: return False
    terms=company_terms_for_filter(company_name)
    cleaned=[]
    for t in terms:
        t=t.lower().replace(' / ',' ').replace('/',' ').replace('-',' ')
        cleaned.extend([x for x in t.split() if len(x)>=3])
    cleaned=list(dict.fromkeys(cleaned))
    return any(host==f'{t}.com' or host==f'{t}.be' or host==f'{t}.eu' or host.endswith(f'.{t}.com') or host.endswith(f'.{t}.be') or host.endswith(f'.{t}.eu') or (t in host.split('.')) for t in cleaned)

def targeted_negative_sources(results, company_name, limit=5):
    kept = []
    for r in results:
        if is_company_owned_source(r, company_name):
            continue
        if is_negative_external_source(r) and source_mentions_company(r, company_name):
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
# This scanner therefore distinguishes consumer-facing pages from investor/stakeholder reports.

GREEN_CLAIMS=[
 (['sustainable','sustainability','green','eco-friendly','environmentally friendly','planet friendly','better for the planet','good for the planet'],'Generic environmental claim','High','EmpCo risk: generic environmental claims need excellent recognised environmental performance relevant to the claim; otherwise the wording may be misleading in B2C communications.','Replace generic wording with specific, evidenced wording, e.g. “This product uses X% recycled material, verified under [scheme], for [scope/period].”'),
 (['carbon neutral','climate neutral','net zero','carbon negative','co2 neutral','carbon compensated','offset','offsetting','compensated emissions'],'Climate-neutrality or offsetting claim','High','EmpCo risk: claims based on greenhouse-gas offsetting that state or imply neutral, reduced or positive climate impact require particular caution and clear separation from real emission reductions.','Separate actual emissions reductions from offsets; disclose scopes, baseline, methodology, residual emissions and offset role.'),
 (['recyclable','recycled','recycled content','made from recycled','circular','circularity','closed loop','reuse','reusable','repairable','durable','biodegradable','compostable'],'Circularity / durability / recyclability claim','Medium','EmpCo risk: environmental and circularity claims can mislead when they omit conditions, product coverage, local infrastructure, durability limits or verification.','Specify the product parts, percentage, conditions, geography, testing standard, repair availability and limitations.'),
 (['less harmful','lower impact','reduced impact','lower emissions','reduced emissions','less co2','lower carbon','energy efficient','water efficient'],'Comparative environmental claim','High','EmpCo risk: comparisons must be clear, objective, based on equivalent products, transparent methodology and up-to-date data.','State the comparator, baseline, methodology, date, scope and data source; avoid vague “better/lower impact” claims.'),
 (['certified','label','eco label','ecolabel','sustainability label','verified','independently verified','approved by'],'Sustainability label / certification claim','Medium','EmpCo risk: sustainability labels should be based on a certification scheme or established by public authorities; otherwise they may be prohibited or misleading.','Name the certification scheme, standard owner, scope, audit/verification basis and validity period.'),
 (['we will be net zero','we aim to be net zero','by 2030','by 2040','by 2050','future environmental performance','transition plan','science based target','sbt'],'Future environmental-performance claim','High','EmpCo risk: future environmental-performance claims require clear, objective, publicly verifiable commitments and a realistic implementation plan.','Add a public implementation plan, milestones, resources, governance, progress indicators and scope limitations.'),
 (['all natural','natural','clean','non-toxic','chemical free','zero impact','no impact','100% sustainable','fully sustainable','always sustainable'],'Absolute or purity environmental wording','High','EmpCo risk: absolute or purity wording may create an overbroad impression and carries a high evidence burden.','Qualify the claim; specify exact attribute, scope, test method, limitations and evidence.'),
]

EMPCO_LENS=[
 {'name':'Directive (EU) 2024/825 / EmpCo','use':'Frames green-claim risk in B2C commercial communications by addressing misleading environmental claims, generic claims, labels, comparisons and future performance claims.'},
 {'name':'UCPD environmental-claim definition','use':'Checks whether a message states or implies positive, zero, reduced, comparative or improved environmental impact of a product, brand or trader.'},
 {'name':'Generic environmental claims','use':'Generic claims such as green, sustainable or environmentally friendly need excellent environmental performance relevant to the claim.'},
 {'name':'Sustainability labels','use':'Labels should be based on a certification scheme or established by public authorities.'},
 {'name':'Future environmental performance','use':'Future claims should be supported by clear, objective, publicly verifiable commitments and implementation plans.'},
 {'name':'Consumer-facing communications','use':'EmpCo has strongest relevance for B2C/commercial communications; investor reports remain relevant as source evidence but are not treated the same as consumer marketing material.'}
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
            'audience':'Investor / stakeholder reporting',
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
        'interpretation':'May combine corporate, commercial and stakeholder language. Treat product, homepage or brochure wording as higher-risk than report-style background text.'
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
        aud='Investor / stakeholder reporting'; emp='Indirect / evidence source'
        note='The reviewed material is mainly annual, ESG, sustainability or investor reporting. Treat it primarily as evidence or context, not as consumer advertising, unless the same claims are reused externally.'
    elif counts.get('internal',0)>0 and counts.get('client_facing',0)==0:
        aud='Policy / internal governance material'; emp='Indirect / governance evidence'
        note='The reviewed material appears to be policy or governance material. It is useful as substantiation evidence, but wording risk is lower than in consumer-facing material.'
    else:
        aud='Mixed channel set'; emp='Mixed'
        note='The scan includes more than one communication channel. The analysis separates client-facing communication from investor/stakeholder reporting and policy/internal governance material.'
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
        return 'Investor / stakeholder report'
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

def detect_green_claims(text):
    low=(text or '').lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in GREEN_CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            seen.add(typ); score=60 if risk=='High' else 38
            fs.append({'dimension':'green','type':typ,'risk':risk,'claim':snip(text,trig),'issue':issue,'rewrite':rewrite,'claim_score':score,'standards':['EmpCo / Directive (EU) 2024/825','UCPD misleading commercial practices'],'action':'Substantiate the green claim with scope, objective evidence, methodology, limits and verification.'})
    if not fs:
        fs.append({'dimension':'green','type':'No major high-risk green claim detected','risk':'Low','claim':(text or '')[:320]+('...' if len(text or '')>320 else ''),'issue':'The crawler did not detect obvious high-risk green-claim wording in the reviewed pages.','rewrite':'Keep environmental claims specific, scoped and supported by verifiable evidence.','claim_score':15,'standards':['General green-claim quality review'],'action':'Keep green claims specific, scoped and evidence-backed.'})
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
    for q in qs[:5]:
        res,attempts=search_public_sources(q,3)
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

GREEN_NEGATIVE_SIGNAL_TERMS=['greenwashing','misleading','complaint','lawsuit','court','regulator','authority','advertising standards','ban','prohibited','investigation','fine','penalty','carbon neutral','offset','sustainable claim','environmental claim']
def is_green_negative_source(result):
    text=(result.get('title','')+' '+result.get('content','')+' '+result.get('url','')).lower()
    return any(t in text for t in GREEN_NEGATIVE_SIGNAL_TERMS)

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
    audience_factor=1.0 if audience.get('audience')=='Consumer-facing / commercial communication' else 0.85 if audience.get('audience')=='Mixed or unclear' else 0.70
    raw=round((claim_wording*0.30 + evidence_gap*0.30 + external_score*0.25 + sector_score*0.15)*audience_factor)
    if no_major: raw=min(raw,28 if external_score<40 else 38)
    if high_claims==0: raw=min(raw,49)
    if evidence_gap<45: raw=min(raw,49)
    if external_score<40: raw=min(raw,59)
    if raw>=80 and not (high_claims>=2 and evidence_gap>=70 and external_score>=65): raw=min(raw,74)
    comps={'claim_wording_risk':claim_wording,'substantiation_risk':evidence_gap,'external_context_risk':external_score,'sector_baseline_risk':sector_score,'substantiation_score':substantiation,'evidence_notes':evidence_notes,'audience_factor':audience_factor}
    return max(0,min(100,raw)), comps, external_context

def combine_green_social(green_score, social_score, audience):
    # Equal-weight integrated score; if there are no clear findings in one dimension, the other dimension still drives half of the overall score.
    # Direct consumer-facing material slightly increases the relevance of green/social claims under B2C unfair-practice logic.
    overall=round((green_score*0.50)+(social_score*0.50))
    if audience.get('audience')=='Consumer-facing / commercial communication': overall=min(100, round(overall*1.05))
    return overall

def green_washing_conclusion(score, findings, evidence_gap, external_score, audience):
    no_major=findings and findings[0].get('type','').lower().startswith('no major')
    prefix='Consumer-facing EmpCo-relevant material: ' if audience.get('audience')=='Consumer-facing / commercial communication' else ''
    if no_major: return prefix+'No clear greenwashing signal detected'
    if score<30: return prefix+'Low green-claim substantiation risk'
    if score<50: return prefix+'Potentially overbroad green claim'
    if score<60: return prefix+'Potential greenwashing concern — evidence review needed'
    if external_score>=40 and evidence_gap>=55: return prefix+'High greenwashing risk signal — verify urgently'
    return prefix+'Potential greenwashing concern — not enough contradiction evidence for High'

def build_green_claim_inventory(findings):
    out=[]
    for f in findings:
        out.append({'dimension':'Green','claim_text':f.get('claim',''),'claim_type':f.get('type',''),'washing_type':f.get('type',''),'risk_level':f.get('risk',''),'claim_score':f.get('claim_score',0),'risk_reason':f.get('issue',''),'analysis':f.get('issue',''),'evidence_needed':green_evidence_checklist(f),'suggested_rewrite':f.get('rewrite',''),'standards':f.get('standards',[])})
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
    client_facing=(audience.get('audience')=='Consumer-facing / commercial communication')
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
    channel_analysis=build_channel_analysis(documents_checked)
    social_fs=detect_claims(txt)
    green_fs=detect_green_claims(txt)
    social_ext=external(comp['company'], social_fs)
    green_ext=external_green(comp['company'], green_fs)
    exttext=' '.join(r.get('title','')+' '+r.get('content','') for r in (social_ext.get('results',[])+green_ext.get('results',[])))
    sec=infer_sector(comp,txt+'\n'+exttext)
    ctx=infer_context(comp,txt,social_ext)
    social_score, social_mod, social_mod_note, evidence_credit, social_components = calc_score(social_fs,sec,ctx,social_ext,txt)
    social_external_context = strict_external_context_risk(social_ext, comp.get('company',''))
    social_components['external_context_risk']=social_external_context.get('score',social_components.get('external_context_risk',0))
    green_score, green_components, green_external_context = calc_green_score(green_fs,sec,green_ext,txt,audience)
    overall=combine_green_social(green_score,social_score,audience)
    social_splits=split_scores(social_fs,sec,ctx,social_mod,social_components)
    green_splits={k:green_components[k] for k in ['claim_wording_risk','substantiation_risk','external_context_risk','sector_baseline_risk']}
    social_conclusion=washing_conclusion(social_score,social_fs,social_splits.get('substantiation_risk',50),social_splits.get('external_context_risk',0))
    green_conclusion=green_washing_conclusion(green_score,green_fs,green_splits.get('substantiation_risk',50),green_splits.get('external_context_risk',0),audience)
    social_targeted=targeted_negative_sources(social_ext.get('results',[]), comp.get('company',''), 5)
    green_targeted=compact_sources([r for r in green_ext.get('results',[]) if is_green_negative_source(r) and source_mentions_company(r,comp.get('company','')) and not is_company_owned_source(r,comp.get('company',''))],5)
    all_claims=build_green_claim_inventory(green_fs)+social_claim_inventory_with_dimension(social_fs)
    all_claims=assign_claim_sources(all_claims,page_segments,documents_checked)
    for c in all_claims:
        c.setdefault('source_url', url)
        c.setdefault('source_label', 'Reviewed website / document')
        c.setdefault('audience_lens', audience.get('audience','Mixed or unclear'))
        c.setdefault('audience_group', 'mixed')
    methodology='Green & Social Claims Risk Assessment. Green claims are assessed through an EmpCo / Directive (EU) 2024/825 lens for consumer-facing environmental claims. Social claims are assessed through claim wording, evidence gap, external contradictory context and sector exposure, with a specific Forced Labour Regulation / Regulation (EU) 2024/3015 lens for product, supplier, import/export, traceability, forced-labour and modern-slavery claims. Clear indications of EmpCo or Forced Labour Regulation risk receive a higher weighting than broader responsible-business claims mainly linked to OECD Guidelines, UNGC or UNGP expectations. Sector exposure is included as a baseline sensitivity factor but should not create a High-risk result without problematic claim wording, evidence gaps or contradictory context.'
    summary=(f"{comp['company']} receives a global green & social claims risk score of {overall}/100. "
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
        'external_research':{'green':dict(green_ext,compact_sources=green_targeted,targeted_negative_sources=green_targeted),'social':dict(social_ext,compact_sources=social_targeted,targeted_negative_sources=social_targeted),'summary':'Green and social external-source layers are reported separately.'},
        'green_external_context_assessment':green_external_context,'social_external_context_assessment':social_external_context,
        'score_components':{'green':green_components,'social':social_components},'split_scores':{'global_score':overall,'green_risk_score':green_score,'social_risk_score':social_score,'green':green_splits,'social':social_splits},
        'why_score':{'global':f'Global score is {overall}/100, calculated from the green and social risk scores with a slight consumer-facing adjustment where applicable.',
                     'green':f"Green risk is {green_score}/100. Claim wording {green_splits.get('claim_wording_risk')}/100; substantiation risk {green_splits.get('substantiation_risk')}/100; external context {green_splits.get('external_context_risk')}/100; sector baseline {green_splits.get('sector_baseline_risk')}/100. {' '.join(green_components.get('evidence_notes',[]))}",
                     'social':f"Social risk is {social_score}/100. Claim wording {social_splits.get('claim_wording_risk')}/100; substantiation risk {social_splits.get('substantiation_risk')}/100; external context {social_splits.get('external_context_risk')}/100; sector baseline {social_splits.get('sector_baseline_risk')}/100. {' '.join(social_components.get('evidence_notes',[]))} Forced-labour/product-supply-chain claims are assessed against Regulation (EU) 2024/3015 readiness where relevant.",
                     'audience':audience['note'],'interpretation':'This is an assessment signal, not a legal finding. EmpCo relevance is strongest for consumer-facing commercial communications.'},
        'stakeholder_red_flags':build_red_flags(social_fs,social_ext,sec,ctx)+(['High-sensitivity green claims require EmpCo-style substantiation and consumer-facing wording controls.'] if any(f.get('risk')=='High' for f in green_fs) else []),
        'company_action_plan':build_green_social_actions(green_fs,social_fs,audience),'engagement_questions':build_engagement_questions(social_fs,social_ext)+['Which green claims are consumer-facing, and what objective evidence file supports each claim under EmpCo-style controls?','For products or supply chains, what forced-labour risk assessment, traceability evidence, remediation process and withdrawal/customs response procedure support the claim under Regulation (EU) 2024/3015?'],
        'confidence':build_confidence(pages,social_ext,social_fs),'disclaimer':'Indicative first-pass green & social claims assessment only. This tool does not provide legal advice, does not establish a violation of EmpCo, the Forced Labour Regulation or any other law, and does not make a definitive greenwashing or social-washing finding. Results should be verified by legal, compliance and subject-matter experts before external use. External search results are review signals that require manual verification.',
        'analysed_text_excerpt':txt[:2200],'quality_improvements':['Maintain a claims register distinguishing green and social claims.','Classify each claim by audience: consumer-facing marketing vs investor/stakeholder reporting.','For forced-labour and modern-slavery claims, link wording to product/supplier traceability, risk assessment, remediation and Regulation (EU) 2024/3015 readiness.','Attach objective evidence, methodology, limitations and approval owner to each claim.','Check public-source context for contradiction signals.'],
        'ai_used':False,'ai_note':''}

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
            self._json({"error":"Unknown endpoint"},404)
        except Exception as e: self._json({"error":str(e)},500)

def main():
    print("Green & Social Claims Risk Assessment v35"); print(f"Serving on http://{HOST}:{PORT}"); print("Tavily configured:",bool(TAVILY_API_KEY)); print("Google Search configured:",bool(GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX)); print("AI configured:",bool(OPENAI_API_KEY)); HTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()
