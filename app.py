#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime

APP_VERSION="hostable_v11"
PORT=int(os.environ.get("PORT","8000"))
HOST="0.0.0.0"
APP_DIR=Path(__file__).resolve().parent
TAVILY_API_KEY=os.environ.get("TAVILY_API_KEY","").strip()
OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY","").strip()

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
 (["supply chain","value chain","all suppliers","supplier","responsible sourcing","ethical sourcing","audited","certified","traceable","supplier code"],"Supply-chain or supplier-responsibility claim","High","The claim may imply supplier control or responsible value-chain coverage without showing supplier tiers, audit quality, worker voice or remediation.","Scope the claim, for example: 'We assess higher-risk suppliers through a risk-based process and disclose supplier coverage, key findings and corrective-action closure rates.'"),
 (["diversity","inclusion","inclusive","equality","equal opportunities","pay equity","gender equality","non-discrimination"],"Diversity, equality and inclusion claim","Medium","The claim refers to inclusion or equality but may not provide workforce data, baseline, targets, pay-equity information or progress evidence.","Add measurable evidence, for example: 'We monitor diversity and inclusion through workforce data, employee feedback and targeted action plans, with progress reported annually.'"),
 (["safe workplace","safe working","health and safety","well-being","wellbeing","worker welfare","quality of life","care for employees"],"Health, safety or worker-welfare claim","High","The claim suggests safe or positive working conditions but may not provide incident data, contractor coverage, workload evidence, worker feedback or remedy.","Link to controls and outcomes, for example: 'We monitor health and safety through incident reporting, training, contractor coverage and corrective actions.'"),
 (["accessibility","vulnerable customers","customer care","fair treatment","customer protection","affordable for all","financial inclusion","digital inclusion"],"Customer welfare or accessibility claim","Medium","The claim concerns customer welfare or inclusion but may not show measurable access, complaints, remedy or vulnerable-customer safeguards.","Add evidence, for example: 'We track accessibility and customer inclusion through service metrics, complaint handling and improvement actions for vulnerable groups.'"),
 (["everyone","all employees","all workers","all suppliers","for all","highest","best","fully","guarantee","zero","always","never","100%"],"Absolute or broad wording","High","Absolute terms may overstate coverage, control or outcomes and create a high evidence burden.","Qualify the wording, for example: replace 'all suppliers meet our highest standards' with 'selected higher-risk suppliers are assessed against our supplier code, with limitations and corrective actions disclosed.'")
]

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
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 SocialClaimRiskScan/11.0","Accept":"text/html,application/xhtml+xml"})
    with urlopen(req,timeout=20,context=ssl.create_default_context()) as r:
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
    for link in cands[:5]:
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
    with urlopen(req,timeout=35) as r: data=json.loads(r.read().decode("utf-8",errors="ignore"))
    return [{"title":i.get("title",""),"url":i.get("url",""),"content":i.get("content",""),"score":i.get("score",0)} for i in data.get("results",[])]
def external(company):
    if not TAVILY_API_KEY: return {"enabled":False,"summary":"External public-source search is not enabled because TAVILY_API_KEY is not configured.","results":[]}
    qs=[company+" human rights labour rights controversy NGO report",company+" workers union strike discrimination lawsuit",company+" supplier supply chain forced labour child labour",company+" regulator complaint customer protection accessibility",company+" social responsibility criticism press investigation"]
    allr=[]; seen=set()
    for q in qs:
        try:
            for r in tavily_search(q,4):
                if r["url"] and r["url"] not in seen: r["query"]=q; allr.append(r); seen.add(r["url"])
        except Exception as e: allr.append({"title":"External search query failed","url":"","content":str(e)[:240],"score":0,"query":q})
    summary=summarise_ext(allr)
    return {"enabled":True,"summary":summary,"results":allr[:16]}
def summarise_ext(results):
    if not results: return "No external public-source results were returned."
    combo=" ".join((r.get("title","")+" "+r.get("content","")).lower() for r in results)
    terms=["forced labour","forced labor","child labour","child labor","lawsuit","complaint","strike","union","ngo","discrimination","human rights","supplier","workers","controversy","regulator"]
    hits=[t for t in terms if t in combo]
    return ("External results contain potentially relevant social-risk signals, including: "+", ".join(hits[:8])+". These require verification.") if hits else "External results were found, but no strong social-risk signal was detected from snippets alone."
def infer_context(company,text,ext):
    combo=(company.get("context","")+" "+text[:20000]+" "+ext.get("summary","")).lower(); level="Medium" if "No recognised" not in company.get("context","") else "Low"
    high=["forced labour","forced labor","child labour","child labor","modern slavery","living wage","lawsuit","strike","union","human rights complaint","discrimination","regulator"]
    med=["complaint","supplier","workers","controversy","ngo","accessibility","vulnerable customers","subcontractor","franchise"]
    if any(t in combo for t in high): level="High"
    elif any(t in combo for t in med) and level=="Low": level="Medium"
    note=company.get("context","")+" External public-source layer: "+ext.get("summary","")
    return {"level":level,"note":note.strip()}
def snip(text,trig):
    l=text.lower(); i=l.find(trig.lower())
    if i<0: return ""
    return " ".join(text[max(0,i-100):min(len(text),i+len(trig)+190)].split())
def detect_claims(text):
    low=text.lower(); fs=[]; seen=set()
    for triggers,typ,risk,issue,rewrite in CLAIMS:
        trig=next((t for t in triggers if t in low),None)
        if trig and typ not in seen:
            seen.add(typ); score=78 if risk=="High" else 52
            fs.append({"type":typ,"risk":risk,"claim":snip(text,trig),"issue":issue,"rewrite":rewrite,"claim_score":score})
    if not fs: fs.append({"type":"No major high-risk social claim detected","risk":"Low","claim":text[:320]+("..." if len(text)>320 else ""),"issue":"The crawler did not detect obvious high-risk social-claim wording in the reviewed company pages.","rewrite":"Keep social claims specific, scoped and supported by measurable evidence.","claim_score":18})
    return sorted(fs,key=lambda f:f["claim_score"],reverse=True)
def level(score):
    return "Very high" if score>=75 else "High" if score>=50 else "Medium" if score>=25 else "Low"
def calc_score(findings,sector,context):
    claim=max(f["claim_score"] for f in findings); s={"Low":0,"Medium":8,"High":15}.get(sector["level"],8); c={"Low":0,"Medium":8,"High":17,"Very high":24}.get(context["level"],0); n=min(8,max(0,len([f for f in findings if f["risk"]=="High"])-1)*3)
    return min(100,round(claim*.65+s+c+n))
def guidance(findings,sector):
    txt=" ".join(f["rewrite"] for f in findings[:2])
    if sector["level"]=="High": txt+=" Because this sector has higher structural exposure, avoid generic wording such as 'ethical', 'fair', 'responsible' or 'for everyone' unless scope, coverage, limitations and remediation evidence are explicit."
    return txt
def build_report(company,sector,context,findings,score,pages):
    top=", ".join(f["type"] for f in findings[:3]); language="high-sensitivity" if any(f["risk"]=="High" for f in findings) else "moderate or low-sensitivity"
    summary=f"{company['company']} receives a {level(score).lower()} social-claim risk score of {score}/100. The assessment is mainly driven by {language} wording around {top}, combined with {sector['level'].lower()} sector exposure and {context['level'].lower()} context sensitivity. The key improvement is to replace broad reassurance language with scoped, measurable and evidence-backed statements."
    rationale=f"Sector risk: {sector['risks']} Basis: {sector['basis']}. Context: {context['note']} The reviewed company pages were screened for social, labour, human-rights, inclusion, customer and value-chain wording. The Tavily layer adds NGO, press, regulator/government and legal/context signals when configured."
    return {"summary":summary,"rationale":rationale,"rewrite_guidance":guidance(findings,sector),"pages_reviewed":pages}
def analyse_url(raw):
    url=norm_url(raw); txt,pages=crawl(url); comp=infer_company(url,txt); ext=external(comp["company"]); exttext=" ".join(r.get("title","")+" "+r.get("content","") for r in ext.get("results",[])); sec=infer_sector(comp,txt+"\n"+exttext); ctx=infer_context(comp,txt,ext); fs=detect_claims(txt); score=calc_score(fs,sec,ctx)
    return {"version":APP_VERSION,"source_label":url,"analysis_date":datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),"overall_score":score,"overall_risk":level(score),"company":comp,"sector":sec,"context":ctx,"findings":fs,"report":build_report(comp,sec,ctx,fs,score,pages),"external_research":ext,"disclaimer":"Indicative first-pass assessment only. It is not legal advice and not a finding that social washing occurred. External search results are review signals that require verification.","analysed_text_excerpt":txt[:2200],"ai_used":False,"ai_note":"AI refinement is not enabled in this clean V11 build unless added later."}

class Handler(BaseHTTPRequestHandler):
    def _send(self,body,ctype="text/html; charset=utf-8",status=200):
        if isinstance(body,str): body=body.encode()
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers(); self.wfile.write(body)
    def _json(self,d,status=200): self._send(json.dumps(d,ensure_ascii=False,indent=2),"application/json; charset=utf-8",status)
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_OPTIONS(self): self._json({"ok":True})
    def do_GET(self):
        if self.path=="/" or self.path.startswith("/?"): self._send((APP_DIR/"frontend.html").read_text(encoding="utf-8"))
        elif self.path=="/api/health": self._json({"status":"ok","version":APP_VERSION,"ai_configured":bool(OPENAI_API_KEY),"tavily_configured":bool(TAVILY_API_KEY)})
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
    print("Social Claim Risk Scan Hostable v11"); print(f"Serving on http://{HOST}:{PORT}"); print("Tavily configured:",bool(TAVILY_API_KEY)); print("AI configured:",bool(OPENAI_API_KEY)); HTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=="__main__": main()
