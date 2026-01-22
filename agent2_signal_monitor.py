import logging
from database import SessionLocal
from models import Company, CompanySignal, ProactiveOutreach, Contact
from utils import call_llm, parse_json_from_llm
import config
import requests
from datetime import datetime
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_news_for_company(company_name: str) -> List[Dict[str, Any]]:
    if not config.NEWS_API_KEY or 'your_' in config.NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {"q": f'"{company_name}"', "sortBy": "publishedAt", "pageSize": 5, "apiKey": config.NEWS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200: return resp.json().get('articles', [])
    except: pass
    return []

def fetch_job_signals(company: Company) -> List[Dict[str, Any]]:
    from jobspy import scrape_jobs
    try:
        jobs = scrape_jobs(site_name=["linkedin", "indeed"], search_term=f'"{company.name}" sales', results_wanted=2, hours_old=168)
        if not jobs.empty: return jobs.to_dict('records')
    except: pass
    return []

def generate_role_aware_email(company, signal_text, contact):
    """Generate a draft email tailored to the recipient's role."""
    role = contact.role_type
    prompt = f"""
    Create a highly personalized outreach email for a senior enterprise sales role.
    Target: {contact.name} ({contact.title}) at {company.name}.
    Context: {signal_text}
    Role Category: {role}
    
    Instructions by Role Category:
    - Founder/CEO: Emphasize "helping you build/scale payer GTM" and "hands-on seller who can own revenue and build motion."
    - CRO/VP Sales: Emphasize "quota-carrying senior IC / player-coach" and specific payer deals.
    - CCO/COO/Other Executive: Emphasize "cross-functional GTM, payer relationships, and implementation awareness."
    
    Candidate Background: {config.USER_PROFILE_SUMMARY}
    
    Return JSON:
    {{
      "outreach_angle": "string summary of the pitch",
      "draft_email": "string text of the email"
    }}
    """
    resp = call_llm(prompt, response_format="json")
    return parse_json_from_llm(resp)

def score_signal(company: Company, signal_text: str):
    prompt = f"""
    Evaluate this signal for {company.name} ({company.vertical}).
    Signal: {signal_text}
    Determine if this is an outreach trigger (High urgency = Funding, Expansion, New Leadership Hire, or multiple new postings).
    Return JSON: {{"is_trigger": bool, "urgency_score": 0-100, "signal_type": "string"}}
    """
    resp = call_llm(prompt, response_format="json")
    return parse_json_from_llm(resp)

def run_signal_monitor():
    db = SessionLocal()
    try:
        active_companies = db.query(Company).filter(Company.monitoring_status == 'active').all()
        for company in active_companies:
            signals_found = []
            
            # 1. News
            articles = fetch_news_for_company(company.name)
            for art in articles:
                signals_found.append({"text": art['title'], "url": art['url'], "type": "news"})
            
            # 2. Jobs
            jobs = fetch_job_signals(company)
            if jobs:
                signals_found.append({"text": f"Hiring for: {jobs[0]['title']}", "url": jobs[0]['job_url'], "type": "hiring"})
            
            for sig in signals_found:
                existing = db.query(CompanySignal).filter(CompanySignal.source_url == sig['url']).first()
                if existing: continue
                
                analysis = score_signal(company, sig['text'])
                if not analysis: continue
                
                new_sig = CompanySignal(
                    company_id=company.id,
                    signal_type=analysis.get('signal_type', sig['type']),
                    signal_date=datetime.now(),
                    signal_text=sig['text'],
                    score=analysis.get('urgency_score', 0),
                    source_url=sig['url']
                )
                db.add(new_sig)
                
                if analysis.get('is_trigger') and analysis.get('urgency_score', 0) >= 50:
                    # Find top contact for this company to personalize outreach
                    contact = db.query(Contact).filter(Contact.company_id == company.id).order_by(Contact.confidence_score.desc()).first()
                    
                    email_draft = {"outreach_angle": "Generic signal trigger", "draft_email": ""}
                    if contact:
                        email_draft = generate_role_aware_email(company, sig['text'], contact)
                    
                    outreach = ProactiveOutreach(
                        company_id=company.id,
                        contact_id=contact.id if contact else None,
                        signal_summary=email_draft.get('outreach_angle'),
                        fit_explanation=f"Trigger: {sig['text']}",
                        draft_email=email_draft.get('draft_email'),
                        priority_score=analysis.get('urgency_score'),
                        status='queued'
                    )
                    db.add(outreach)
            db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    run_signal_monitor()
