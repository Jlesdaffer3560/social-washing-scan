#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from pathlib import Path
import json, os, ssl, socket, ipaddress, datetime
PORT=int(os.environ.get('PORT','8000')); HOST='0.0.0.0'; APP_DIR=Path(__file__).resolve().parent; MAX_TEXT_CHARS=60000
BENCHMARK='UCPD/Directive 2024/825; ESRS S1-S4; CSDDD; UNGPs; OECD Guidelines; ILO standards; GRI reporting quality'
COMPONENTS=[('claim_severity','Claim severity',25,'Strength, breadth and sensitivity of the social claim.'),('evidence_gap','Substantiation quality / evidence gap',20,'Whether evidence, scope, methodology and metrics are missing or unclear.'),('controversy_context','Company-specific controversy or enforcement context',25,'Public controversy, litigation, labour dispute, NGO/NCP complaint or enforcement sensitivity.'),('stakeholder_vulnerability','Stakeholder vulnerability and remedy gap',15,'Exposure to low-wage workers, migrant workers, children, vulnerable consumers, affected communities or weak remedy.'),('sector_modifier','Sector risk modifier',15,'Structural exposure from sector model, value chain, workforce intensity or consumer/community impact.')]
SECTORS={'Low':3,'Medium':8,'High':14}
PROFILES={
'kbc':('KBC','Banking and financial services','Medium',42,'Medium','Policy-based reporting reduces risk; main exposure is broad responsible-banking, inclusion and positive-impact language.','Responsible banking, customer protection, financial inclusion, accessibility, employee well-being, diversity, business ethics, privacy and human-rights expectations in financing and supplier relationships.','Frameworks referenced include UNGPs, ILO principles, OECD Guidelines and modern-slavery related requirements where relevant.','No confirmed social-washing finding identified. Residual risk relates to broad responsible-banking, financial-inclusion, customer-protection and societal-impact claims.','The reporting is relatively structured and policy-based. Residual risk is that broad language such as responsible banking, positive impact or inclusion can overstate outcomes if not linked to measurable client outcomes, escalation decisions, grievance handling and vulnerable-customer safeguards.','No confirmed social-washing finding identified; medium risk because broad responsible-banking, inclusion and positive-impact language depends on credible human-rights due diligence across lending, investment and procurement.','responsible banking; positive societal impact; inclusive finance; sustainable investment; human-rights respect; fair treatment of customers','Medium risk. KBC should ensure social-impact and responsible-finance claims are specific, scoped to relevant activities, and linked to due-diligence outcomes, exclusions, grievance channels and customer-protection evidence.'),
'delhaize':('Delhaize','Food retail and supermarkets','Medium',62,'High','Company-specific risk is driven by franchise labour sensitivity and food-supply-chain human-rights exposure.','Own workforce, franchise relations, health and safety, diversity, responsible sourcing, food affordability, community support, product quality and human-rights due diligence in food supply chains.','Mainly through Ahold Delhaize group reporting: social-compliance programmes, supplier standards and human-rights due diligence.','Material controversy flags identified, including franchise-related labour/social-dialogue sensitivity in Belgium and supply-chain human-rights exposure.','Food retail combines low-margin employment, franchise models, supplier pressure, farm-labour exposure and consumer-affordability claims. Risk is higher where responsible employer or caring retailer claims are not scoped between own stores, franchise operations and suppliers.','High company-level risk due to social-purpose claims, franchise-related labour controversy in Belgium and human-rights exposure in food supply chains.','caring employer; responsible retailer; fair supply chain; better for everyone; community value; inclusive workplace; ethical sourcing','High risk. Delhaize should avoid broad social-responsibility or fair-work claims unless franchise boundaries, worker coverage, supplier due diligence and remedy mechanisms are transparent.'),
'zara':('Zara / Inditex','Fast fashion and apparel retail','High',82,'Very high','Very high risk due to fast-fashion supply chains, worker-rights exposure and broad ethical/sustainable-fashion claims.','Supply-chain management, supplier audits, worker welfare, human rights, traceability, responsible purchasing, health and safety in factories, diversity and community programmes.','Human Rights Policy, due-diligence processes, ILO conventions, UN Global Compact principles and grievance mechanisms.','Material controversy flags identified, including forced-labour and supplier-labour allegations and scrutiny connected to Xinjiang/Uyghur forced-labour concerns.','Extensive reporting does not remove high inherent risk. Claims about ethical, responsible or audited supply chains can be undermined by purchasing pressure, subcontracting, wage issues, audit limitations and weak worker voice.','Very high company-level risk due to fast-fashion supply chains, social-audit reliance, labour-rights allegations and public concern about ethical-production claims.','ethical; responsible; audited; worker welfare; respect for human rights; traceable supply chain; certified factory','Very high risk. Zara/Inditex social claims should be reviewed at product and supply-chain level with strong evidence, worker voice, remediation data, supplier-tier transparency and clear limitations.'),
'fluxys':('Fluxys','Gas infrastructure and energy transport','Medium',56,'High','Energy infrastructure risk is linked to safety, just transition, communities and responsible-transition claims.','Safety, operational reliability, employee and contractor health and safety, diversity, stakeholder engagement, local-community relations, emergency preparedness, responsible procurement and human rights.','Ethical-code materials refer to the Universal Declaration of Human Rights, ILO Conventions and OECD Guidelines.','No confirmed social-washing case identified. Main exposure is linked to worker and contractor safety, community impacts, emergency preparedness, just-transition claims and stakeholder trust.','Social-washing risk arises where broad claims about responsible infrastructure, good neighbour relations or enabling society are not supported by contractor safety, community engagement, incident response, grievance mechanisms and emergency communication evidence.','High-end medium risk: own-workforce governance appears developed, but gas infrastructure involves safety, contractors, affected communities and imported-energy human-rights exposure.','responsible energy infrastructure; good neighbour; respect for human rights; safe workplace; sustainable value chain; enabling society','High-end medium risk. Fluxys should ensure broad social and energy-transition claims include boundaries and due-diligence evidence for workers, suppliers and affected communities.')}
RULES=[('ethical fair responsible worker-friendly socially responsible socially sustainable trusted','Broad ethical or responsible-business claim','High','Consumers, workers, value-chain workers, communities or customers','Broad ethical wording reassures users about responsible conduct but may not specify what is covered or how it is verified.','Claim-specific evidence, due-diligence process, scope, exclusions, third-party verification, grievance channels and remediation outcomes.','We apply defined responsible-business criteria to a specific activity and disclose scope, methodology and limitations.',18,16,9,'UCPD/Directive 2024/825; OECD Guidelines; UNGPs; GRI','ESRS S1/S2/S3/S4 depending on claim scope'),('human rights labour rights forced labour forced labor child labour child labor living wage modern slavery decent work','Human-rights or fundamental labour-rights claim','High','Own workers, value-chain workers, vulnerable workers or affected communities','The statement refers to human rights or labour rights but may not evidence due diligence, salient risks, grievance access or remediation.','Human-rights policy, salient-risk assessment, due-diligence steps, stakeholder engagement, grievance mechanism, tracking and remedy evidence.','We assess selected human-rights risks through a risk-based due-diligence process and follow up identified issues through corrective actions.',21,17,13,'UNGPs; OECD Guidelines; ILO Fundamental Principles; CSDDD; ESRS S1/S2','ESRS S1 Own workforce / ESRS S2 Workers in the value chain'),('supply chain value chain all suppliers suppliers respect responsible sourcing ethical sourcing supplier code audited supply chain certified','Supply-chain or supplier-responsibility claim','High','Supplier workers, contractors, migrant/seasonal workers, farmers or communities','The wording may imply control over suppliers or a responsible value chain without demonstrating coverage, verification or remediation.','Supplier-tier scope, supplier code, audit methodology, worker interviews, non-compliance cases, corrective-action closure rate and grievance channels.','We assess higher-risk suppliers through a risk-based due-diligence process and disclose coverage, findings and corrective-action progress.',22,18,13,'CSDDD; UNGPs; OECD Guidelines; ILO; ESRS S2','ESRS S2 Workers in the value chain'),('diversity inclusion inclusive equality equal opportunities pay equity gender equality non-discrimination belonging','Diversity, equality and inclusion claim','Medium','Employees, candidates, customers or affected groups','The claim refers to diversity, equality or inclusion but may not provide data, scope, baseline or progress evidence.','Workforce diversity metrics, pay-equity data, baseline, targets, inclusion survey, action plan and governance owner.','We monitor diversity and inclusion using workforce data, employee feedback and targeted initiatives, with progress disclosed for the reporting period.',14,14,8,'ESRS S1; ILO; GRI; UCPD/Directive 2024/825','ESRS S1 Own workforce'),('safe workplace safe working health and safety well-being wellbeing worker welfare care for employees quality of life','Health, safety or worker-welfare claim','High','Own workers, contractors and outsourced workers','The wording suggests safe or positive working conditions but may not show controls, KPIs or outcome data.','Incident rates, LTIFR, contractor coverage, safety audits, worker feedback, workload data, grievance cases and corrective actions.','We monitor worker health and safety through incident reporting, training, risk assessments and corrective actions covering employees and relevant contractors.',18,15,11,'ILO; ESRS S1; GRI; UCPD/Directive 2024/825','ESRS S1 Own workforce'),('accessibility vulnerable customers customer care fair treatment customer protection affordable for all financial inclusion digital inclusion','Customer welfare, accessibility or inclusion claim','Medium','Consumers, end-users, vulnerable customers or passengers','The claim concerns customer or end-user welfare but may not show measurable outcomes, limitations, complaints or remedy.','Accessibility metrics, complaints, remedy process, vulnerable-customer safeguards, incident data, affordability criteria and service-quality outcomes.','We track customer inclusion and accessibility through defined metrics, complaint handling and improvement actions for identified vulnerable groups.',14,13,10,'ESRS S4; UCPD/Directive 2024/825; GRI','ESRS S4 Consumers and end-users'),('community good neighbour affected communities local value community support social value enabling society positive impact social impact people first','Community impact or social-value claim','Medium','Affected communities, local residents or civil society','The claim suggests positive community or social value but may not show impact measurement, stakeholder engagement or grievance access.','Stakeholder engagement, impact assessment, community KPIs, grievance channels, remediation actions and limitations.','We engage with affected communities and disclose the scope, outcomes and limitations of our community-impact actions.',15,14,9,'ESRS S3; UNGPs; OECD Guidelines; GRI','ESRS S3 Affected communities'),('everyone all employees all workers all suppliers for all highest best fully guarantee zero always never 100%','Absolute or broad wording','High','All stakeholders mentioned or implied by the claim','The claim contains absolute wording that may overstate coverage, control or outcomes.','Coverage percentage, scope, exceptions, methodology, assurance, limitations and evidence trail.','Replace absolute wording with scoped, evidence-based wording that explains what is covered and what remains in progress.',19,16,8,'UCPD/Directive 2024/825; GRI reporting quality principles','Cross-cutting claim-quality issue')]
class P(HTMLParser):
    def __init__(self): super().__init__(); self.skip=False; self.parts=[]
    def handle_starttag(self,t,a):
        if t.lower() in {'script','style','noscript','svg','canvas','form'}: self.skip=True
    def handle_endtag(self,t):
        if t.lower() in {'script','style','noscript','svg','canvas','form'}: self.skip=False
    def handle_data(self,d):
        if not self.skip:
            c=' '.join(d.split())
            if len(c)>2: self.parts.append(c)
def clean(html):
    p=P(); p.feed(html); seen=set(); lines=[]
    for raw in p.parts:
        low=raw.lower()
        if low not in seen: seen.add(low); lines.append(raw)
    return '\n'.join(lines)[:MAX_TEXT_CHARS]
def private(host):
    if host in {'localhost','127.0.0.1','0.0.0.0'}: return True
    try:
        for r in socket.getaddrinfo(host,None):
            ip=ipaddress.ip_address(r[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: return True
    except Exception: return False
    return False
def fetch(url):
    u=urlparse(url)
    if u.scheme not in ('http','https') or not u.hostname: raise ValueError('Invalid URL')
    if private(u.hostname): raise ValueError('Private/local URLs are blocked')
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 SocialWashingScan/7.0','Accept':'text/html'})
    with urlopen(req,timeout=18,context=ssl.create_default_context()) as r:
        if 'html' not in r.headers.get('content-type','').lower(): raise ValueError('URL does not return HTML')
        return clean(r.read(2000000).decode('utf-8','ignore'))
def level(score): return 'Very high' if score>=75 else 'High' if score>=50 else 'Medium' if score>=25 else 'Low'
def sector_risk(s):
    t=(s or '').lower();
    if any(x in t for x in ['fast fashion','apparel','discount','food retail','supermarket','catering','facilities','outsourced','commodity','platform']): return 'High'
    return 'Medium' if s else 'Medium'
def snip(text,trig):
    l=text.lower(); i=l.find(trig.lower())
    if i<0: return ''
    return ' '.join(text[max(0,i-90):min(len(text),i+len(trig)+160)].split())
def detect(text):
    l=text.lower(); out=[]; seen=set()
    for terms,ctype,risk,stake,issue,evid,rewrite,sev,gap,vuln,bench,esrs in RULES:
        trig=next((w for w in terms.split() if w in l),None)
        # better phrase matching
        for phrase in terms.split('  '):
            pass
        words=terms.split()
        # also match multiword known chunks
        chunks=[terms]
        for candidate in ['human rights','supply chain','value chain','responsible sourcing','ethical sourcing','health and safety','financial inclusion','digital inclusion','positive impact','social impact','people first','all suppliers','all employees','for all']:
            if candidate in terms: chunks.append(candidate)
        trig=next((c for c in chunks+words if c and c in l),trig)
        if not trig: continue
        key=ctype+trig
        if key in seen: continue
        seen.add(key)
        score=min(100,round(sev/25*35+gap/20*30+vuln/15*20+(15 if risk=='High' else 8)))
        out.append({'claim':snip(text,trig),'trigger':trig,'claim_type':ctype,'risk':risk,'benchmark':bench,'esrs_mapping':esrs,'stakeholder_group':stake,'detected_issue':issue,'risk_rationale':issue+' '+('This increases risk where claims are broad, consumer-facing or not supported by due-diligence evidence.'),'evidence_gap':evid,'suggested_rewrite':rewrite,'claim_score':score,'subscores':{'claim_severity':sev,'evidence_gap':gap,'stakeholder_vulnerability':vuln},'remediation_status':'Open - requires substantiation review'})
    return sorted(out or [{'claim':text[:280],'trigger':'','claim_type':'No major social-washing keyword detected','risk':'Low','benchmark':'General claim-quality review','esrs_mapping':'Not mapped','stakeholder_group':'General stakeholders','detected_issue':'No obvious high-risk wording detected.','risk_rationale':'This does not confirm substantiation; context and evidence still require review.','evidence_gap':'Evidence and context should still be checked manually.','suggested_rewrite':'Use precise wording linked to measurable actions, reporting period and scope.','claim_score':18,'subscores':{'claim_severity':4,'evidence_gap':6,'stakeholder_vulnerability':3},'remediation_status':'Monitor'}],key=lambda f:f['claim_score'],reverse=True)
def profile(name):
    k=(name or '').lower()
    for key,val in PROFILES.items():
        if key in k or k in key: return val
    return None
def components(findings,sect,cont,prof):
    if prof:
        score=prof[3]; sec=SECTORS[prof[2]]; controversy=5 if score<50 else 13 if score<65 else 19 if score<75 else 23; claim=min(25,max(8,round(score*.25))); gap=min(20,max(7,round(score*.20))); vuln=max(4,score-claim-gap-controversy-sec); return {'claim_severity':claim,'evidence_gap':gap,'controversy_context':controversy,'stakeholder_vulnerability':vuln,'sector_modifier':sec}
    msev=max(f['subscores']['claim_severity'] for f in findings); mgap=max(f['subscores']['evidence_gap'] for f in findings); mv=max(f['subscores']['stakeholder_vulnerability'] for f in findings); c={'None':0,'Low':5,'Medium':12,'High':20,'Very high':25}.get(cont,0); return {'claim_severity':msev,'evidence_gap':mgap,'controversy_context':c,'stakeholder_vulnerability':mv,'sector_modifier':SECTORS[sect]}
def record(company,sector,sect,findings,comp,score,prof):
    if prof:
        return {'company':prof[0],'sector':prof[1],'sector_social_risk_score':prof[2],'final_socialcheck_result':f'{prof[4]} social-washing risk; risk score {prof[3]}/100.','short_assessment_summary':prof[5],'relevant_benchmark':BENCHMARK,'company_reported_social_topics_reviewed':prof[6],'frameworks_referenced':prof[7],'controversy_check':prof[8],'socialcheck_analysis':prof[9],'risk_rationale':prof[10],'potential_socialcheck_flags':prof[11],'conclusion':prof[12]}
    cats=', '.join(sorted(set(f['claim_type'] for f in findings))[:4]); flags='; '.join(sorted(set(f['trigger'] for f in findings if f['trigger'])))
    return {'company':company or 'Company / page reviewed','sector':sector or 'Not specified','sector_social_risk_score':sect,'final_socialcheck_result':f'{level(score)} social-washing risk; risk score {score}/100.','short_assessment_summary':'Risk is driven by detected social-claim wording, evidence gaps, sector exposure and selected controversy context.','relevant_benchmark':BENCHMARK,'company_reported_social_topics_reviewed':'Detected topics include: '+(cats or 'no major claim category detected')+'.','frameworks_referenced':'Not verified in this automated scan. Check whether the company references UNGPs, OECD Guidelines, ILO, GRI, ESRS S1-S4 or sector due-diligence frameworks.','controversy_check':'Not independently verified by the tool. Use the controversy/context selector or add manual notes where public controversies are relevant.','socialcheck_analysis':'The scan identified potential social-claim signals mainly linked to '+(cats or 'general claim quality')+'. The assessment combines page-level claim wording with sector exposure and selected controversy context.','risk_rationale':'Final score combines claim severity, evidence gap, controversy context, stakeholder vulnerability/remedy gap and sector modifier.','potential_socialcheck_flags':flags or 'No major keyword flag detected.','conclusion':f'{level(score)} risk. The company should keep social claims specific, scoped and supported by clear evidence, while documenting limitations and reporting boundaries.'}
def analyse(text,src,company='',sector='',cont='None'):
    prof=profile(company); sect=prof[2] if prof else sector_risk(sector); findings=detect(text); comp=components(findings,sect,cont,prof); score=prof[3] if prof else min(100,sum(comp.values())); rec=record(company,sector,sect,findings,comp,score,prof)
    return {'version':'hostable_v7','source_label':src,'analysis_date':datetime.datetime.utcnow().isoformat(timespec='seconds')+'Z','overall_score':score,'overall_risk':level(score),'sector_risk':sect,'sector_profile':{'interpretation':'Sector risk is a contextual modifier and does not automatically determine final company score.'},'scoring_components':[{'key':k,'label':lab,'max':mx,'description':desc,'score':comp[k]} for k,lab,mx,desc in COMPONENTS],'summary':{'main_conclusion':rec['conclusion'],'main_score_driver':rec['risk_rationale'],'short_assessment_summary':rec['short_assessment_summary']},'detailed_record':rec,'findings':findings,'audit_ready_export_fields':['company','URL/source','claim','claim type','stakeholder group','benchmark','ESRS mapping','evidence gap','score','rationale','suggested rewrite','remediation status'],'disclaimer':'This is an indicative desktop-style SocialCheck assessment, not a legal finding. A high score means the sector, claims or public context require stronger substantiation; it does not mean the company has committed social washing.','analysed_text_excerpt':text[:2500]}
class H(BaseHTTPRequestHandler):
    def send(self,b,ct='text/html; charset=utf-8',status=200):
        if isinstance(b,str): b=b.encode('utf-8')
        self.send_response(status); self.send_header('Content-Type',ct); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.end_headers(); self.wfile.write(b)
    def j(self,d,status=200): self.send(json.dumps(d,ensure_ascii=False,indent=2),'application/json; charset=utf-8',status)
    def do_OPTIONS(self): self.j({'ok':True})
    def do_GET(self):
        if self.path=='/' or self.path.startswith('/?'): self.send((APP_DIR/'frontend.html').read_text(encoding='utf-8'))
        elif self.path=='/api/health': self.j({'status':'ok','version':'hostable_v7'})
        else: self.j({'error':'Not found'},404)
    def do_POST(self):
        try:
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))).decode('utf-8') or '{}'); company=data.get('company_name',''); sector=data.get('sector',''); cont=data.get('controversy_level','None')
            if self.path=='/api/scan/text':
                text=data.get('text','')
                if not text.strip(): return self.j({'error':'No text provided'},400)
                return self.j(analyse(text[:MAX_TEXT_CHARS],data.get('source_label','Manual text input'),company,sector,cont))
            if self.path=='/api/scan/url':
                url=data.get('url','')
                if not url: return self.j({'error':'No URL provided'},400)
                return self.j(analyse(fetch(url),url,company,sector,cont))
            self.j({'error':'Unknown endpoint'},404)
        except Exception as e: self.j({'error':str(e)},500)
def main(): print('Social Washing Scan Hostable v7'); print(f'Serving on http://{HOST}:{PORT}'); HTTPServer((HOST,PORT),H).serve_forever()
if __name__=='__main__': main()
