import os
import sys
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import ProactiveOutreach, Company, Job, CompanySignal
from scoring import score_lead

def run_scoring(test_run_id: str, scoring_version: str):
    db = SessionLocal()
    try:
        leads = db.query(ProactiveOutreach).filter(ProactiveOutreach.test_run_id == test_run_id).all()
        print(f"Scoring {len(leads)} leads for test_run_id: {test_run_id}, version: {scoring_version}")
        
        for lead in leads:
            company = db.query(Company).get(lead.company_id)
            job = db.query(Job).get(lead.job_id) if lead.job_id else None
            signals = db.query(CompanySignal).filter(CompanySignal.company_id == lead.company_id).all()
            
            new_score = score_lead(company, job=job, signals=signals)
            
            # Auto-Flagging Candidates
            expected_tier = (lead.test_scores or {}).get("expected_tier")
            flag_it = False
            reason = ""
            
            if expected_tier == "high" and new_score < 60:
                flag_it = True
                reason = f"High expected, but got {new_score}"
            elif expected_tier == "low" and new_score > 60:
                flag_it = True
                reason = f"Low expected, but got {new_score}"
                
            if flag_it:
                from models import CandidateGoldenLead
                import uuid
                # Check if already a candidate
                existing = db.query(CandidateGoldenLead).filter(CandidateGoldenLead.company_name == company.name).first()
                if not existing:
                    candidate = CandidateGoldenLead(
                        id=str(uuid.uuid4()),
                        company_name=company.name,
                        vertical=company.vertical,
                        location=company.hq_location,
                        actual_fit_score=new_score,
                        actual_lead_type=lead.lead_type,
                        reason_flagged=reason,
                        source_outreach_id=lead.id
                    )
                    db.add(candidate)
                    print(f"  🚩 Flagged {company.name} as Golden Lead candidate: {reason}")

            # Update test_scores JSON
            current_scores = lead.test_scores or {}
            current_scores[scoring_version] = new_score
            lead.test_scores = current_scores
            
            print(f"  {company.name}: {new_score}")
        
        db.commit()
        print(f"✅ Scoring complete for version {scoring_version}")
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run-id", default="golden_set_v1")
    parser.add_argument("--version", default="v2")
    args = parser.parse_args()
    
    run_scoring(args.test_run_id, args.version)
