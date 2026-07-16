"""Regression test: claim risk labels must remain inside every claim card."""
import io
from pathlib import Path
import fitz
from pypdf import PdfReader
import report_pdf

sample = {
    'company': {'company':'SHEIN'},
    'source_label':'https://www.shein.com',
    'original_url':'https://www.shein.com',
    'analysis_date':'2026-07-16T12:00:00+00:00',
    'global_score':47,'global_risk':'Medium','green_score':61,'green_risk':'Medium','social_score':27,'social_risk':'Low',
    'entity_context_indicator': {'level':'High','note':'Ten relevant external signals were retained.'},
    'data_reliability_warning': "4 reviewed pages required a public text-extraction fallback. A low risk score from this scan may reflect limited access to the site's content, not necessarily a genuine absence of risky claims.",
    'claim_inventory':[
        {'claim_type':'Future environmental-performance claim with an exceptionally long title that previously pushed the risk label outside the right-hand border','risk_level':'Very high','claim_score':95,'matched_phrase':'decarbonization roadmap','claim_text':'We are developing a comprehensive decarbonization roadmap which will chart out a pathway to achieve our near-term target to reduce emissions by 25% by 2030.','why_flagged':'This future environmental-performance claim requires a detailed, measurable and verifiable implementation plan.','evidence_needed':['scope of the claim','specific environmental attribute','reporting period','methodology','limitations and exclusions'],'suggested_rewrite':'Add a public implementation plan, milestones, resources, governance, progress indicators, verification basis and scope limitations.','source_label':'2023 sustainability and social impact report'},
        {'claim_type':'Absolute or purity environmental wording','risk_level':'High','claim_score':90,'matched_phrase':'zero waste','claim_text':'Two of these facilities obtained Zero Waste to Landfill certification, independently assured by TÜV Rheinland.','why_flagged':'Absolute wording creates a high evidence burden.','evidence_needed':['scope','methodology','reporting period'],'suggested_rewrite':'Qualify the claim and specify exact scope, conditions, test method, limitations and evidence.','source_label':'2023 sustainability and social impact report'},
        {'claim_type':'Generic environmental claim','risk_level':'High','claim_score':86,'matched_phrase':'more sustainable','claim_text':'SHEIN and Lufthansa Cargo sign an MoU to promote more sustainable air transportation.','why_flagged':'The environmental attribute and baseline are unclear.','evidence_needed':['attribute','baseline','method'],'suggested_rewrite':'Specify the exact attribute, baseline and evidence.','source_label':'2024 sustainability and social impact report'},
    ],
    'company_action_plan':[{'title':'Review client-facing green claims under EmpCo','action':'Review all consumer-facing claims.'},{'title':'Build a claim evidence file','action':'Create claim-specific files.'},{'title':'Align reporting and marketing language','action':'Add approval controls.'}],
    'report': {'pages_reviewed':['https://www.shein.com','https://www.shein.com/sustainability','https://www.sheingroup.com/report','https://www.sheingroup.com/people']},
    'confidence': {'level':'Medium','reasons':['several company pages were reviewed','external public-source search was active','claim-level signals were detected']},
    'external_research': {'green': {'targeted_negative_sources':[
        {'title':'Shein faces greenwashing investigation in Italy','url':'https://example.com/shein-investigation','source_name':'ESG publication','published_date':'2026-06-01','status':'Investigation / regulatory review','review_status':'Retained - manual verification required','content':'The authority opened an investigation into environmental claims.','related_claim_area':'Environmental claims','entity_match':'Direct - target in title'},
        {'title':'Shein fined for misleading environmental claims','url':'https://example.org/shein-fine','source_name':'News source','published_date':'2026-07-01','status':'Decision / ruling','review_status':'Retained - manual verification required','content':'The authority imposed a fine for misleading environmental claims.','related_claim_area':'Environmental claims','entity_match':'Direct - target in title'},
    ]}, 'social': {'targeted_negative_sources':[]}},
}

pdf = report_pdf.build_company_report_pdf(sample)
reader = PdfReader(io.BytesIO(pdf))
assert len(reader.pages) == 2, len(reader.pages)

# All text must stay within the page. In addition, claim-card risk labels now sit
# in the left badge zone, far away from the right border.
doc = fitz.open(stream=pdf, filetype='pdf')
page_w = doc[0].rect.width
for page in doc:
    for word in page.get_text('words'):
        x0,y0,x1,y1,txt,*_ = word
        assert x0 >= -0.5 and x1 <= page.rect.width + 0.5, (page.number, txt, x0, x1)

# Locate risk words in the lower half of page 1 (material card) and upper half
# of page 2 (additional cards). They must be near the left margin, not at the
# right edge of the card.
risk_words = []
for page_no, page in enumerate(doc):
    for x0,y0,x1,y1,txt,*_ in page.get_text('words'):
        if txt.lower() in {'high','very'}:
            if (page_no == 0 and y0 > 360) or (page_no == 1 and y0 < 420):
                risk_words.append((page_no, txt, x0, x1, y0))
assert risk_words, 'No claim-card risk words found'
assert any(x0 < 130 for _,_,x0,_,_ in risk_words), risk_words
assert all(x1 < page_w - 40 for _,_,_,x1,_ in risk_words), risk_words

out = Path('PREVIEW_V66')
out.mkdir(exist_ok=True)
(out/'v66_claim_risk_badge_layout_preview.pdf').write_bytes(pdf)
print('V66 claim-risk badge layout test passed')
