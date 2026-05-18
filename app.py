#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime

PORT = int(os.environ.get('PORT','8000'))
HOST = '0.0.0.0'
APP_DIR = Path(__file__).resolve().parent
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY','').strip()
OPENAI_MODEL = os.environ.get('OPENAI_MODEL','gpt-5-mini')
MAX_TEXT = 90000

KNOWN = {
 'kbc':('KBC','Banking and financial services','Medium','Responsible-finance, customer-protection, inclusion and human-rights-due-diligence claims are sensitive because financing and investment decisions can have indirect social impacts.'),
 'delhaize':('Delhaize','Food retail and supermarkets','High','Food retail can involve franchise labour, supplier pressure, farm-labour exposure, affordability claims and value-chain human-rights risks.'),
 'aldi':('Aldi','Discount food retail','High','Discount food retail has heightened exposure to purchasing practices, agricultural supply chains, migrant or seasonal labour and responsible-sourcing claims.'),
 'lidl':('Lidl','Discount food retail','High','Discount food retail has heightened exposure to purchasing practices, agricultural supply chains, migrant or seasonal labour and responsible-sourcing claims.'),
 'zara':('Zara / Inditex','Fast fashion and apparel retail','High','Fast fashion supply chains are highly exposed to labour-rights, subcontracting, wage, audit-quality, traceability and worker-voice issues.'),
 'inditex':('Inditex / Zara','Fast fashion and apparel retail','High','Fast fashion supply chains are highly exposed to labour-rights, subcontracting, wage, audit-quality, traceability and worker-voice issues.'),
 'fluxys':('Fluxys','Gas infrastructure and energy transport','Medium','Energy infrastructure has exposure to safety, contractor management, communities, emergency preparedness, procurement and transition-related claims.'),
 'sodexo':('Sodexo','Catering, facilities management and outsourced services','High','Outsourced catering and facilities work can involve frontline labour, low-margin contracts, contractor coverage, migrant workers, workload and wage risks.'),
 'bnp':('BNP Paribas / Fortis','Banking and sustainable finance','Medium','Responsible-finance and human-rights claims are sensitive because financing decisions may be connected to high-risk sectors or geographies.'),
 'proximus':('Proximus','Telecommunications and digital services','Medium','Telecom social claims may concern digital inclusion, vulnerable consumers, privacy, cybersecurity, supply-chain labour and responsible digitalisation.')
}
SECTOR_TERMS = [
 ('High',['fast fashion','apparel','textile','garment','fashion','clothing','discount','supermarket','grocery','food retail','catering','facilities','outsourced','platform','delivery','gig','cocoa','palm oil','coffee','cotton'],'high exposure to low-wage work, complex supply chains, migrant or seasonal labour, supplier pressure, audit limitations and worker-voice challenges'),
 ('Medium',['bank','finance','insurance','telecom','digital','aviation','airline','transport','chemical','energy','infrastructure','manufacturing','industrial','technology','utility','gas','logistics'],'meaningful exposure to social impacts, customer rights, contractor management, responsible procurement, safety, data/privacy or affected-community expectations'),
 ('Low',['software','consulting','professional services','agency','office services'],'lower structural exposure, although broad social claims still require evidence')]
CONTEXT = [('Very high',['forced labour','forced labor','child labour','child labor','modern slavery','xinjiang','uyghur','living wage','migrant workers','low wages','human rights complaint']),('High',['strike','labour dispute','labor dispute','union','grievance','ncp complaint','lawsuit','ngo report','allegation','controversy','supplier non-compliance','audit failure']),('Medium',['complaint','accessibility','vulnerable customers','contractor','subcontractor','affected communities','privacy incident','restructuring','franchise'])]
RULES = [
 ('Broad positive-impact claim','Medium',['positive impact','social impact','people first','support society','better for everyone','social value','community impact'],'The wording suggests positive social outcomes but does not clearly define scope, affected groups, metrics, outcomes or limitations.','Broad social-impact language can overstate outcomes if it is not linked to measurable actions, targets, results and limitations.','Refer to specific stakeholder groups, actions and measured outcomes.'),
 ('Broad ethical or responsible-business claim','High',['ethical','fair','responsible','trusted','socially responsible','caring','worker-friendly'],'The wording reassures users about responsible conduct, but may not specify the criteria, scope, exclusions, verification method or evidence.','Generic ethical or responsible-business claims carry a high evidence burden because they can influence trust, purchasing or investment decisions.','Replace broad wording with evidence-based language that explains scope, criteria, limitations and progress.'),
 ('Human-rights or labour-rights claim','High',['human rights','labour rights','labor rights','decent work','forced labour','forced labor','child labour','child labor','living wage','modern slavery'],'The claim refers to sensitive rights topics but may not show due diligence, salient risks, grievance channels, tracking or remedy.','Human-rights claims are sensitive because they relate to potentially severe impacts on affected people.','State the due-diligence process, priority risks, grievance channels and remediation progress.'),
 ('Supply-chain or supplier-responsibility claim','High',['supply chain','value chain','all suppliers','supplier','responsible sourcing','ethical sourcing','audited','certified','traceable','supplier code'],'The claim may imply supplier control or responsible value-chain coverage without showing supplier tiers, audit quality, worker voice or remediation.','Supplier claims are high risk where supplier tiers, audit quality, worker voice and corrective-action closure are unclear.','Scope the claim and disclose supplier coverage, key findings, limitations and corrective-action closure rates.'),
 ('Diversity, equality and inclusion claim','Medium',['diversity','inclusion','inclusive','equality','equal opportunities','pay equity','gender equality','non-discrimination'],'The claim refers to inclusion or equality but may not provide workforce data, baseline, targets, pay-equity information or progress evidence.','D&I claims can become reputationally sensitive if they are not supported by workforce data, targets or concrete actions.','Add measurable workforce data, baseline, targets, action plans and annual progress.'),
 ('Health, safety or worker-welfare claim','High',['safe workplace','safe working','health and safety','well-being','wellbeing','worker welfare','quality of life','care for employees'],'The claim suggests safe or positive working conditions but may not provide incident data, contractor coverage, workload evidence, worker feedback or remedy.','Worker-welfare claims concern worker protection and require evidence on actual conditions, incidents, workload and remedy.','Link the claim to incident data, contractor coverage, training, risk controls and corrective actions.'),
 ('Customer welfare or accessibility claim','Medium',['accessibility','vulnerable customers','customer care','fair treatment','customer protection','affordable for all','financial inclusion','digital inclusion'],'The claim concerns customer welfare or inclusion but may not show measurable access, complaint, remedy or vulnerable-customer safeguards.','Claims about inclusion, accessibility and care can be misleading if vulnerable groups, affordability, complaints and remedy are not addressed.','Use measurable service, accessibility, complaint handling and vulnerable-customer safeguards.'),
 ('Absolute or broad wording','High',['everyone','all employees','all workers','all suppliers','for all','highest','best','fully','guarantee','zero','always','never','100%'],'Absolute terms may overstate coverage, control or outcomes and create a high evidence burden.','Words such as all, fully, highest or guarantee can mislead if exceptions or limitations exist.','Qualify absolute wording with scope, coverage, exclusions, methodology and limitations.')]

class Parser(HTMLParser):
 def __init__(self): super().__init__(); self.skip=False; self.parts=[]; self.links=[]; self.skip_tags={'script','style','noscript','svg','canvas','form'}
 def handle_starttag(self,tag,attrs):
  if tag.lower() in self.skip_tags: self.skip=True
  if tag.lower()=='a':
   for k,v in attrs:
    if k.lower()=='href' and v: self.links.append(v)
 def handle_endtag(self,tag):
  if tag.lower() in self.skip_tags: self.skip=False
 def handle_data(self,data):
  if not self.skip:
   c=' '.join(data.split())
   if len(c)>2: self.parts.append(c)

def parse_html(html):
 p=Parser(); p.feed(html); seen=set(); lines=[]
 for line in '\n'.join(p.parts).splitlines():
  line=' '.join(line.split()); low=line.lower()
  if len(line)>2 and low not in seen: lines.append(line); seen.add(low)
 return '\n'.join(lines), p.links

def private_host(host):
 if host in {'localhost','127.0.0.1','0.0.0.0'}: return True
 try:
  for r in socket.getaddrinfo(host,None):
   ip=ipaddress.ip_address(r[4][0])
   if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return True
 except Exception: return False
 return False

def normalize_url(u):
 u=u.strip()
 if not u: raise ValueError('Please enter a company website URL.')
 if not u.startswith(('http://','https://')): u='https://'+u
 return u

def fetch_html(u):
 pr=urlparse(u)
 if pr.scheme not in ('http','https') or not pr.hostname: raise ValueError('Invalid URL.')
 if private_host(pr.hostname): raise ValueError('Private, local and internal URLs are blocked for safety.')
 req=Request(u,headers={'User-Agent':'Mozilla/5.0 SocialClaimRiskScan/10.0','Accept':'text/html,application/xhtml+xml'})
 with urlopen(req,timeout=18,context=ssl.create_default_context()) as resp:
  ctype=resp.headers.get('content-type','')
  if 'html' not in ctype.lower(): raise ValueError('This URL does not seem to return an HTML page.')
  return resp.read(2000000).decode('utf-8',errors='ignore')

def relevant(h): return any(k in h.lower() for k in ['sustain','responsib','people','human','rights','divers','inclusion','supplier','ethic','governance','impact','community','accessibility','safety','annual','report','esg'])
def same_domain(u,host):
 h=urlparse(u).hostname or ''; return h==host or h.endswith('.'+host)

def crawl(url):
 html=fetch_html(url); host=urlparse(url).hostname or ''; text,links=parse_html(html); pages=[url]; collected=[text]; cands=[]
 for href in links:
  full=urljoin(url,href).split('#')[0]
  if same_domain(full,host) and relevant(full) and full not in cands and full!=url: cands.append(full)
 for link in cands[:5]:
  try:
   t,_=parse_html(fetch_html(link))
   if len(t)>200: collected.append('\n\nPAGE: '+link+'\n'+t); pages.append(link)
  except Exception: pass
 return '\n\n'.join(collected)[:MAX_TEXT], pages

def level(score): return 'Very high' if score>=75 else 'High' if score>=50 else 'Medium' if score>=25 else 'Low'
def infer_company(url,text):
 combo=(url+' '+text[:4000]).lower()
 for k,p in KNOWN.items():
  if k in combo: return {'name':p[0],'sector':p[1],'profile_sector':p[2],'profile_context':p[3]}
 host=urlparse(url).hostname or ''; name=host.replace('www.','').split('.')[0].title() if host else 'Company reviewed'
 return {'name':name,'sector':'Sector not explicitly identified','profile_sector':'','profile_context':''}
def infer_sector(company,text):
 combo=(company.get('sector','')+' '+text[:12000]).lower()
 if company.get('profile_sector'): lev=company['profile_sector']; basis='recognised company/sector profile'
 else:
  lev='Medium'; basis='default medium exposure'
  for l,terms,risks in SECTOR_TERMS:
   hits=[t for t in terms if t in combo]
   if hits: lev=l; basis='matched terms: '+', '.join(hits[:5]); break
 risks=next(r for l,t,r in SECTOR_TERMS if l==lev)
 return {'level':lev,'risks':risks,'basis':basis}
def infer_context(company,text):
 combo=(company.get('profile_context','')+' '+text[:20000]).lower(); lev='Low' if not company.get('profile_context') else 'Medium'; sig=[]
 for l,terms in CONTEXT:
  hits=[t for t in terms if t in combo]
  if hits:
   sig+=hits
   if l=='Very high': lev='Very high'; break
   if l=='High' and lev!='Very high': lev='High'
   if l=='Medium' and lev not in ['Very high','High']: lev='Medium'
 note=company.get('profile_context') or 'No strong company-specific controversy signal was detected in the crawled website text. This is not a full external media/NGO/regulator search.'
 if sig: note+=' Signals found in available text: '+', '.join(sorted(set(sig))[:8])+'.'
 return {'level':lev,'note':note,'signals':sorted(set(sig))[:8]}
def snip(text,trig):
 low=text.lower(); i=low.find(trig.lower())
 if i<0: return ''
 return ' '.join(text[max(0,i-100):min(len(text),i+len(trig)+190)].split())
def claims(text):
 low=text.lower(); out=[]; seen=set()
 for typ,risk,trigs,issue,rat,rewrite in RULES:
  trig=next((t for t in trigs if t.lower() in low),None)
  if not trig or typ in seen: continue
  seen.add(typ); score=78 if risk=='High' else 52 if risk=='Medium' else 22
  out.append({'claim':snip(text,trig),'trigger':trig,'type':typ,'risk':risk,'issue':issue,'rationale':rat,'rewrite':rewrite,'claim_score':score})
 if not out:
  out.append({'claim':text[:320]+('...' if len(text)>320 else ''),'trigger':'','type':'No major high-risk social claim detected','risk':'Low','issue':'The crawler did not detect obvious high-risk wording in the crawled pages.','rationale':'This does not prove that claims are fully substantiated. It only means no major rule-based signal was detected in available website text.','rewrite':'Keep social claims specific, scoped and supported by measurable evidence.','claim_score':18})
 return sorted(out,key=lambda f:f['claim_score'],reverse=True)
def calc(findings,sector,context):
 claim=max(f['claim_score'] for f in findings); sector_add={'Low':0,'Medium':8,'High':15}.get(sector['level'],8); context_add={'Low':0,'Medium':8,'High':15,'Very high':22}.get(context['level'],0); extra=min(8,max(0,len([f for f in findings if f['risk']=='High'])-1)*3)
 return min(100,round(claim*.65+sector_add+context_add+extra))
def guidance(findings,sector):
 txt=' '.join(f['rewrite'] for f in findings[:2])
 if sector['level']=='High': txt+=' Because the sector has higher structural exposure, avoid generic claims such as ethical, fair, responsible or for everyone unless scope, coverage, limitations and remediation evidence are explicit.'
 return txt

def build(company,sector,context,findings,score,pages,url):
 lev=level(score); top=', '.join(f['type'] for f in findings[:3]); sensitive='high-sensitivity' if any(f['risk']=='High' for f in findings) else 'moderate or low-sensitivity'
 summary=f"{company['name']} receives a {lev.lower()} social-claim risk score of {score}/100. The assessment is mainly driven by {sensitive} wording around {top}, combined with {sector['level'].lower()} sector exposure. The key improvement is to replace broad reassurance language with scoped, measurable and evidence-backed statements."
 rationale=f"The sector profile points to {sector['risks']}. The context review indicates: {context['note']} The crawled company pages were screened for social, labour, human-rights, inclusion, customer and value-chain wording. The tool does not yet perform a full public web search across NGO, government, regulator and press sources; that requires integration of a search API. Where external screening is required, this result should be treated as a company-website assessment with contextual risk indicators."
 return {'summary':summary,'rationale':rationale,'rewrite_guidance':guidance(findings,sector),'pages_reviewed':pages}

def ai_refine(result,text):
 if not OPENAI_API_KEY:
  result['ai_used']=False; result['ai_note']='AI refinement is not enabled. Add OPENAI_API_KEY in Render environment variables to activate it.'; return result
 prompt={'task':'Refine this social-claim risk assessment. Keep the same JSON keys. Improve summary, rationale, rewrite_guidance and findings. Do not invent external facts beyond the crawled text and context.','current_result':result,'text_excerpt':text[:25000]}
 try:
  payload={'model':OPENAI_MODEL,'input':'Return only valid JSON. '+json.dumps(prompt,ensure_ascii=False)}
  req=Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+OPENAI_API_KEY,'Content-Type':'application/json'},method='POST')
  raw=urlopen(req,timeout=65).read().decode('utf-8',errors='ignore'); data=json.loads(raw); out=data.get('output_text','')
  if not out:
   for item in data.get('output',[]):
    for c in item.get('content',[]):
     if c.get('type') in ('output_text','text'): out+=c.get('text','')
  s=out.find('{'); e=out.rfind('}')
  if s>=0 and e>s:
   refined=json.loads(out[s:e+1]); refined['ai_used']=True; refined['ai_note']='AI refinement was applied to improve narrative quality. It did not perform live external web search.'; return refined
 except Exception as exc:
  result['ai_note']='AI refinement failed; rule-based narrative used. Error: '+str(exc)[:160]
 result['ai_used']=False; return result

def analyze(raw_url):
 url=normalize_url(raw_url); text,pages=crawl(url); company=infer_company(url,text); sector=infer_sector(company,text); context=infer_context(company,text); findings=claims(text); score=calc(findings,sector,context); report=build(company,sector,context,findings,score,pages,url)
 result={'version':'hostable_v9','source_label':url,'analysis_date':datetime.datetime.utcnow().isoformat(timespec='seconds')+'Z','overall_score':score,'overall_risk':level(score),'company':company,'sector':sector,'context':context,'findings':findings,'report':report,'external_screening_note':'The tool currently reviews the company website and selected same-domain pages. Full screening of NGO, government, regulator and press sources requires a search API integration.','disclaimer':'Indicative first-pass assessment only. It is not legal advice and not a finding that social washing occurred.','analysed_text_excerpt':text[:2200]}
 return ai_refine(result,text)

class Handler(BaseHTTPRequestHandler):
 def _send(self,body,ctype='text/html; charset=utf-8',status=200):
  if isinstance(body,str): body=body.encode()
  self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.end_headers(); self.wfile.write(body)
 def _json(self,data,status=200): self._send(json.dumps(data,ensure_ascii=False,indent=2),'application/json; charset=utf-8',status)
 def do_OPTIONS(self): self._json({'ok':True})
 def do_GET(self):
  if self.path=='/' or self.path.startswith('/?'): self._send((Path(__file__).resolve().parent/'frontend.html').read_text(encoding='utf-8'))
  elif self.path=='/api/health': self._json({'status':'ok','version':'hostable_v9','ai_configured':bool(OPENAI_API_KEY)})
  else: self._json({'error':'Not found'},404)
 def do_POST(self):
  try:
   raw=self.rfile.read(int(self.headers.get('Content-Length',0))).decode(); data=json.loads(raw or '{}')
   if self.path=='/api/scan/url': self._json(analyze(data.get('url',''))); return
   self._json({'error':'Unknown endpoint'},404)
  except Exception as exc: self._json({'error':str(exc)},500)
if __name__=='__main__':
 print('Social Claim Risk Scan Hostable v10'); print(f'Serving on http://{HOST}:{PORT}'); print('AI configured:', bool(OPENAI_API_KEY)); HTTPServer((HOST,PORT),Handler).serve_forever()
