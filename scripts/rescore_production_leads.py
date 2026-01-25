import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import ProactiveOutreach, Company, Job, CompanySignal
from scoring import score_lead

def rescore_all_leads():
    db = SessionLocal()
    try:
        # Fetch all queued leads that are NOT part of a test run
        leads = db.query(ProactiveOutreach).filter(
            ProactiveOutreach.status == 'queued',
            ProactiveOutreach.test_run_id == None
        ).all()
        
        print(f"Rescoring {len(leads)} production leads...")
        
        for lead in leads:
            company = db.query(Company).get(lead.company_id)
            job = db.query(Job).get(lead.job_id) if lead.job_id else None
            signals = db.query(CompanySignal).filter(CompanySignal.company_id == lead.company_id).all()
            
            new_score = score_lead(company, job=job, signals=signals)
            
            old_score = lead.fit_score
            lead.fit_score = new_score
            
            if new_score != old_score:
                print(f"  {company.name}: {old_score} -> {new_score}")
        
        db.commit()
        print("✅ Finished re-scoring production leads.")
    finally:
        db.close()

if __name__ == "__main__":
    rescore_all_leads()
