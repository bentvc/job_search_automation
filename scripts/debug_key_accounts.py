import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import Company, ProactiveOutreach, Job, CompanySignal, GoldenLead
from scoring import score_lead

def debug_accounts(names=None):
    if not names:
        names = ["Gravie", "Molina Healthcare", "Evolent", "Experity", "GitLab"]
    
    db = SessionLocal()
    try:
        print(f"{'Company':<25} {'Score':<6} {'Vertical':<15} {'Type':<15} {'Expected':<10}")
        print("-" * 80)
        
        for name in names:
            # Find in production table
            company = db.query(Company).filter(Company.name.ilike(f"%{name}%")).first()
            if not company:
                print(f"❌ {name} not found in companies table")
                continue
                
            lead = db.query(ProactiveOutreach).filter(ProactiveOutreach.company_id == company.id, ProactiveOutreach.test_run_id == None).first()
            if not lead:
                print(f"⚠️ {company.name} has no production lead in Inbox")
                # Still score the company context
                job = db.query(Job).filter(Job.company_id == company.id).first()
                signals = db.query(CompanySignal).filter(CompanySignal.company_id == company.id).all()
            else:
                job = db.query(Job).get(lead.job_id) if lead.job_id else None
                signals = db.query(CompanySignal).filter(CompanySignal.company_id == company.id).all()

            # Check Golden Lead status
            golden = db.query(GoldenLead).filter(GoldenLead.company_name.ilike(f"%{name}%")).first()
            expected = golden.expected_fit_tier if golden else "N/A"
            gv = golden.vertical if golden else "N/A"

            # Get breakdown
            bd = score_lead(company, job=job, signals=signals, return_breakdown=True)
            
            print(f"{company.name:<25} {bd['final_score']:<6} {company.vertical or 'None':<15} {lead.lead_type if lead else 'None':<15} {expected:<10}")
            print(f"  > Breakdown: Vert:{bd['vertical_score']}, Type:{bd['lead_type_score']}, Loc:{bd['location_score']}, Sig:{bd['signal_score']}, Role:{bd['role_adjustment']}, Global:{bd['global_adjustment']}")
            if golden and company.vertical != golden.vertical:
                print(f"  🚩 VERTICAL MISMATCH: Production='{company.vertical}', Golden='{golden.vertical}'")
                
    finally:
        db.close()

if __name__ == "__main__":
    debug_accounts()
