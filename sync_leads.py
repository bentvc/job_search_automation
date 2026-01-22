import logging
from database import SessionLocal
from models import Job, ProactiveOutreach, Company, Contact
import uuid
from datetime import datetime
from utils import call_llm, parse_json_from_llm
import config
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_cold_intro(company_data):
    """Generate a cold intro for a high-fit company. Input is a tuple of (company, contact)."""
    company, contact = company_data
    if not contact: return None
    
    prompt = f"""
    Generate a short, professional cold outreach email.
    Target: {contact.name} ({contact.title}) at {company.name}.
    Vertical: {company.vertical}
    Context: Senior ICR / Player-coach with $90M+ track record in health plan sales.
    Return JSON: {{"draft_email": "string", "outreach_angle": "string"}}
    """
    try:
        resp = call_llm(prompt, response_format="json")
        analysis = parse_json_from_llm(resp)
        return (company.id, contact.id, analysis)
    except Exception as e:
        logger.error(f"LLM Error for {company.name}: {e}")
        return None

def sync_leads():
    db = SessionLocal()
    try:
        # 1. Link jobs to companies
        jobs = db.query(Job).filter(Job.company_id == None).all()
        for j in jobs:
            if not j.company_name: continue
            co = db.query(Company).filter(Company.name.ilike(j.company_name)).first()
            if co: j.company_id = co.id
        db.commit()

        # 2. Sync shortlisted jobs (Reactive)
        shortlisted = db.query(Job).filter(Job.status == 'shortlisted').all()
        for j in shortlisted:
            if not j.company_id: continue
            existing = db.query(ProactiveOutreach).filter(
                ProactiveOutreach.company_id == j.company_id,
                ProactiveOutreach.signal_summary.like(f"Job: %")
            ).first()
            
            if not existing:
                logger.info(f"Drafting reactive lead for {j.company_name}")
                contact = db.query(Contact).filter(Contact.company_id == j.company_id).order_by(Contact.confidence_score.desc()).first()
                outreach = ProactiveOutreach(
                    id=str(uuid.uuid4()), company_id=j.company_id, contact_id=contact.id if contact else None,
                    outreach_type='intro', signal_summary=f"Job: {j.title}",
                    fit_explanation=f"Responding to posting: {j.title}",
                    draft_email=f"Hi {contact.name if contact else 'Team'},\n\nI saw your posting for {j.title} and wanted to reach out...",
                    priority_score=95, status='queued'
                )
                db.add(outreach)
        
        # 3. Proactive: Pull ALL high-fit companies into queue
        top_universe = db.query(Company).filter(Company.fit_score >= 80).all()
        logger.info(f"Checking universe for {len(top_universe)} high-fit companies...")
        
        drafts_needed = []
        for co in top_universe:
            existing = db.query(ProactiveOutreach).filter(ProactiveOutreach.company_id == co.id).first()
            if not existing:
                contact = db.query(Contact).filter(Contact.company_id == co.id).order_by(Contact.confidence_score.desc()).first()
                if contact:
                    drafts_needed.append((co, contact))
        
        if drafts_needed:
            logger.info(f"Generating drafts for {len(drafts_needed)} target companies...")
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(generate_cold_intro, drafts_needed))
            
            for res in results:
                if res:
                    co_id, con_id, analysis = res
                    outreach = ProactiveOutreach(
                        id=str(uuid.uuid4()), company_id=co_id, contact_id=con_id,
                        outreach_type='intro', signal_summary="Direct Universe Outreach",
                        fit_explanation="High-fit strategic target in Universe.",
                        draft_email=analysis.get('draft_email'),
                        priority_score=90, status='queued'
                    )
                    db.add(outreach)
        
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    sync_leads()
